"""Classify where an item comes from ("obtain sources").

Every rule maps raw client text (set names, m_Reason, m_Description,
m_DesignNotes) to a normalized category. Each category says whether the
item can be obtained on the local private server: "yes" (store, packs,
chests, Wheel of Fate, implemented PvE), "no" (historical: Kickstarter,
ladder seasons, conventions, ...) or "unknown".
Manual corrections go into sources_overrides.json (see apply_overrides).
"""
import json
import re

from . import config

# category -> obtainable on the private server
CATEGORIES = {
    "Booster": "yes",
    "Store": "yes",
    "Starter Deck": "yes",
    "Treasure Chest": "yes",
    "Wheel of Fate": "yes",
    "Campaign": "yes",
    "Campaign Reward": "yes",
    "Server Tournament": "yes",
    "Default": "yes",
    # the server's FRA awards gold and generic chests, no arena-specific loot
    "Frost Ring Arena": "unknown",
    "Arena": "unknown",
    "Adventure Zone 2": "unknown",
    "Promo Pack": "unknown",
    "Kismet's Reserve": "unknown",
    "Account Leveling": "unknown",
    "Unknown": "unknown",
    "Kickstarter": "no",
    "Ladder": "no",
    "Tournament": "no",
    "Holiday": "no",
    "Convention": "no",
    "Anniversary": "no",
    "VIP": "no",
    "Collector Deck": "no",
    "Special": "no",
    "Not Collectible": "no",
}

MAIN_SETS = {
    1: "Shards of Fate", 2: "Shattered Destiny", 3: "Armies of Myth",
    4: "Primal Dawn", 5: "Herofall", 6: "Scars of War", 7: "Frostheart",
    8: "Dead of Winter", 9: "Doombringer",
}
_SET_BY_NAME = {v.lower(): k for k, v in MAIN_SETS.items()}
_SET_BY_NAME.update({"scars": 6, "doombringercorecommons": 9,
                     "frostheart core commons": 7})


def set_no_from_text(text):
    """'Set03_PvE_Promo' -> 3, 'Set 4 Chest loot' -> 4, 'Herofall WOF' -> 5."""
    t = (text or "").lower()
    m = re.search(r"set\s*0*(\d)\b|set0*(\d)", t)
    if m:
        return int(m.group(1) or m.group(2))
    for name, no in sorted(_SET_BY_NAME.items(), key=lambda kv: -len(kv[0])):
        if name in t:
            return no
    return None


def classify_set(name):
    """Card set name -> (set kind, main set number or None)."""
    n = name.lower()
    no = set_no_from_text(name)
    if "alternates" in n:
        kind = "alternate"
    elif "kickstarter" in n:
        kind = "kickstarter"
    elif "pve_promo" in n:
        kind = "pve_promo"
    elif "holiday" in n:
        kind = "holiday"
    elif "arena" in n:
        kind = "arena"
    elif n.startswith(("az1", "az2")):
        kind = "equipment_variant" if "equipment" in n else "campaign"
    elif "basic_shards" in n:
        kind = "basic"
    elif any(k in n for k in ("ai only", "created", "talents", "npcs", "oddities")):
        kind = "not_collectible"
    elif "core commons" in n or "corecommons" in n:
        kind = "main"
    elif name in MAIN_SETS.values():
        kind = "main"
    else:
        kind = "not_collectible"
    return kind, no


def src(category, detail="", raw="", set_no=None):
    return {"category": category, "detail": detail, "raw": raw or "",
            "set_no": set_no, "obtainable": CATEGORIES[category]}


def not_here(source):
    """A source that existed in HEX but is not handed out by this server."""
    return {**source, "obtainable": "no"}


def set_label(no):
    return MAIN_SETS.get(no, f"Set {no}") if no else ""


# ---------------------------------------------------------------- cards

BOOSTER_RARITIES = ("Common", "Uncommon", "Rare", "Legendary")


def server_loot():
    """Card prize lists of the server's chests and Wheels of Fate, by card name:
    {"chest_aa": {name: set_guid}, "wheel_aa": ..., "wheel_pve": ...,
     "chest_pve": {name: set_guid}, "pve_promo_sets": {promo set guid: [set guid]}}.
    Imported from ref/hex-server/services; empty if unavailable."""
    import sys
    sys.path.insert(0, str(config.HEX_SERVER_SRC))
    try:
        from services import chest_loot, wheel_of_fate
    except Exception as e:  # server source missing or changed
        print(f"warning: server loot lists unavailable: {e}", file=sys.stderr)
        return None
    finally:
        sys.path.remove(str(config.HEX_SERVER_SRC))

    def by_name(table):
        return {n: s for s, names in table.items() for n in names}

    chest_aa = {n: s for s, tiers in chest_loot.CHEST_AA_CARDS.items()
                for names in tiers.values() for n in names}
    promo_sets = {}
    for main_set, promo in chest_loot.PVE_PROMO_SETS.items():
        promo_sets.setdefault(promo, []).append(main_set)
    return {"chest_aa": chest_aa, "wheel_aa": by_name(wheel_of_fate.WOF_AA_CARDS),
            "wheel_pve": by_name(wheel_of_fate.WOF_PVE_CARDS),
            "chest_pve": by_name(chest_loot.CHEST_PVE_CARDS),
            "chest_pve_rarities": chest_loot._PVE_CARD_RARITIES["any"],
            "pve_promo_sets": promo_sets}


def card_sources(card, set_info, ctx_sources, booster_sets, loot, set_no_of):
    """Sources of a card. card: name/rarity/set_guid; set_info: kind/set_no/name;
    ctx_sources come from relations (starter decks, rewards); booster_sets are
    the set numbers the server sells boosters for; loot is server_loot();
    set_no_of maps a set guid to its main set number."""
    out = list(ctx_sources)
    set_kind, set_no, set_name = set_info["kind"], set_info["set_no"], set_info["name"]
    name, rarity = card["name"], card["rarity"]
    label = set_label(set_no)
    loot = loot or {}
    if rarity == "Land" and set_kind != "basic":
        return [src("Not Collectible", "Token, only created by other cards", set_name)]
    if set_kind == "main" and rarity == "Epic":
        found = False
        for key, cat in (("chest_aa", "Treasure Chest"), ("wheel_aa", "Wheel of Fate")):
            if loot.get(key, {}).get(name) == card["set_guid"]:
                out.append(src(cat, f"{label} {cat.lower() if cat == 'Treasure Chest' else cat} (alternate art)",
                               set_name, set_no))
                found = True
        if not found:
            out.append(not_here(src("Treasure Chest", f"{label} chests or Wheel of Fate (alternate art), "
                                    "not in this server's prize lists", set_name, set_no)))
    elif set_kind == "main":
        if rarity in BOOSTER_RARITIES:
            cat = "Booster" if set_no in booster_sets else "Unknown"
            out.append(src(cat, f"{label} booster packs", set_name, set_no))
        else:
            out.append(src("Unknown", f"{rarity} card of {label}", set_name, set_no))
    elif set_kind == "alternate":
        out.append(src("Unknown", f"{label} alternate art, not in this server's prize lists",
                       set_name, set_no))
    elif set_kind == "pve_promo":
        wheel_set = loot.get("wheel_pve", {}).get(name)
        mains = loot.get("pve_promo_sets", {}).get(card["set_guid"], [])
        if wheel_set:
            no = set_no_of.get(wheel_set)
            out.append(src("Wheel of Fate", f"{set_label(no)} Wheel of Fate (PvE card)", set_name, no))
        elif mains and rarity in loot.get("chest_pve_rarities", ()):
            # Sets sharing one promo set list their chest cards; the last set takes the rest
            chest_set = loot.get("chest_pve", {}).get(name)
            if chest_set is None:
                listed = set(loot.get("chest_pve", {}).values())
                rest = [m for m in mains if m not in listed]
                chest_set = rest[0] if rest else None
            no = set_no_of.get(chest_set)
            if chest_set:
                out.append(src("Treasure Chest", f"{set_label(no)} chests (PvE card)", set_name, no))
        if len(out) == len(ctx_sources):
            out.append(not_here(src("Treasure Chest", f"{label} chests or Wheel of Fate (PvE card), "
                                    "not in this server's prize lists", set_name, set_no)))
    elif set_kind == "campaign":
        cat = "Adventure Zone 2" if set_name.lower().startswith("az2") else "Campaign"
        if not any(s["category"] == "Campaign Reward" for s in out):
            out.append(src(cat, set_name, set_name))
    elif set_kind == "arena":
        wheel_set = loot.get("wheel_pve", {}).get(name)
        if wheel_set:
            no = set_no_of.get(wheel_set)
            out.append(src("Wheel of Fate", f"{set_label(no)} Wheel of Fate (PvE card)", set_name, no))
        out.append(src("Arena", set_name, set_name))
    elif set_kind == "kickstarter":
        out.append(src("Kickstarter", "Kickstarter backer card", set_name))
    elif set_kind == "holiday":
        out.append(src("Holiday", set_name, set_name))
    elif set_kind == "basic":
        out.append(src("Default", "Granted to every new account", set_name))
    elif set_kind == "equipment_variant":
        out.append(src("Not Collectible", "Card version created by equipment", set_name))
    else:
        out.append(src("Not Collectible", set_name, set_name))
    return out


# ---------------------------------------------------------------- items

_REASON_RULES = [
    (r"awarded to all (?:accounts|players)", "Special", None),
    (r"to (?:the )?([\w' -]+?) Tier Kickstarter", "Kickstarter", lambda m: f"{m.group(1)} Tier backers"),
    (r"kickstarter", "Kickstarter", None),
    (r"wheels?\s*of\s*fate|\bwof\b|wofset|^wheels$", "Wheel of Fate", None),
    (r"chest", "Treasure Chest", None),
    (r"booster pack", "Booster", None),
    (r"\bstore\b", "Store", None),
    (r"all players have|everyone has", "Default", None),
    (r"starter mercenary", "Default", None),
    (r"account leveling", "Account Leveling", None),
    (r"ladder", "Ladder", None),
    (r"kismet", "Kismet's Reserve", None),
    (r"\bkr\b", "Kismet's Reserve", None),
    (r"adventure zone ii|\baz2\b|brutecrown|kraken|great machine graveyard|kukatan|malthane", "Adventure Zone 2", None),
    (r"\baz1\b|fort romor|devonshire|usurper|smoldering|tranquil dream|crayburn|campaign", "Campaign", None),
    (r"siege pack|cosmic coin pack|silver talon|pack\b", "Promo Pack", None),
    (r"tournament|invitational|gauntlet|clash|bash|showdown|conclave|merry melee|draft", "Tournament", None),
    (r"holiday|questmas|questmus|abundance|ardor day|night of bells|harvest|hallows|sea festival", "Holiday", None),
    (r"gencon|gen con|convention|conv\b|convocation|anime friends", "Convention", None),
    (r"anniversary", "Anniversary", None),
    (r"vip", "VIP", None),
    (r"collector deck|dragon's blood deck|blood dragon deck", "Collector Deck", None),
    (r"\bfra\b", "Frost Ring Arena", None),
    (r"arena", "Arena", None),
    (r"chronicles of entrath|alachian sea", "Campaign", None),
    (r"alpha|beta|charity|exalted|bugs|employee|special reward|poster|logging in|promotion", "Special", None),
]


def text_sources(text):
    """Classify a free-text origin (m_Reason / m_Description / m_DesignNotes)."""
    raw = (text or "").strip()
    first = raw.splitlines()[0].strip() if raw else ""
    if not first:
        return [src("Unknown")]
    for pattern, cat, detail in _REASON_RULES:
        m = re.search(pattern, first, re.I)
        if m:
            d = detail(m) if detail else _detail_for(cat, first)
            return [src(cat, d, raw, set_no_from_text(first))]
    return [src("Unknown", first, raw)]


def _detail_for(cat, text):
    no = set_no_from_text(text)
    if cat in ("Treasure Chest", "Wheel of Fate", "Booster") and no:
        return f"{set_label(no)} {cat.lower() if cat != 'Wheel of Fate' else 'Wheel of Fate'}"
    return text.rstrip(".")


def apply_overrides(sources_by_guid, path):
    """Overrides file: {"<guid>": [{"category": ..., "detail": ...}, ...]}."""
    try:
        with open(path, encoding="utf-8") as f:
            overrides = json.load(f)
    except FileNotFoundError:
        return 0
    for g, lst in overrides.items():
        sources_by_guid[g] = [src(s["category"], s.get("detail", ""), "override") for s in lst]
    return len(overrides)
