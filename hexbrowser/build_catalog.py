"""Build cache/catalog.sqlite from the client gamedata and the server's static tables.

Static data only; player data is read live from hconnect.db by account.py.
The server DB is opened read-only.

Usage: python -m hexbrowser.build_catalog
"""
import collections
import json
import sqlite3
import sys

from . import config, sources
from .gamedata import art_name, guid, load, short_type

ITEM_KINDS = {
    "InventoryEquipmentData": "equipment",
    "InventoryMercenaryData": "mercenary",
    "InventoryDeckSleeve": "sleeve",
    "InventoryGameboardData": "gameboard",
    "InventoryCoinData": "coin",
    "InventoryGemData": "gem",
    "InventoryCardPack": "pack",
    "InventoryStarterPack": "starter",
    "InventoryTreasureChest": "chest",
    "InventoryStardust": "stardust",
    "InventoryCompTicket": "ticket",
    "InventoryVIPProduct": "vip",
    "InventoryCurrencyData": "currency",
}
COLLECTIBLE_KINDS = {"card", "equipment", "mercenary", "sleeve", "gameboard", "coin", "gem"}
# Gems have no art number; the client draws them from the orb textures in
# cardsets/herofallgems.harc: one pair (bronze ring, dark ring) per shard color.
GEM_ART = {"Blood": ("a0006842", "a0006843"), "Diamond": ("a0006844", "a0006845"),
           "Ruby": ("a0006846", "a0006847"), "Sapphire": ("a0006848", "a0006849"),
           "Wild": ("a0006850", "a0006851"), None: ("a0007367", "a0007368")}

SCHEMA = """
CREATE TABLE sets (guid TEXT PRIMARY KEY, name TEXT, set_no INTEGER, kind TEXT,
                   release_date TEXT, bundle TEXT);
CREATE TABLE items (
    guid TEXT PRIMARY KEY, kind TEXT, name TEXT, set_guid TEXT, set_name TEXT,
    set_no INTEGER, set_kind TEXT, rarity TEXT, type TEXT, subtype TEXT,
    faction TEXT, cost INTEGER, threshold_json TEXT, attack INTEGER,
    defense INTEGER, text TEXT, flavor TEXT, artist TEXT, art TEXT,
    icon TEXT, image TEXT, pve INTEGER, tradeable INTEGER, is_promo INTEGER,
    is_unique INTEGER, max_copies INTEGER, is_alternate INTEGER,
    base_guid TEXT, collectible INTEGER, obtainable TEXT, art_crop TEXT, extra_json TEXT);
CREATE TABLE sources (item_guid TEXT, category TEXT, detail TEXT, raw_text TEXT,
                      set_no INTEGER, obtainable TEXT);
CREATE TABLE relations (from_guid TEXT, rel TEXT, to_guid TEXT, qty INTEGER);
CREATE INDEX idx_items_kind ON items(kind, name);
CREATE INDEX idx_sources_item ON sources(item_guid);
CREATE INDEX idx_sources_cat ON sources(category);
CREATE INDEX idx_rel_from ON relations(from_guid, rel);
CREATE INDEX idx_rel_to ON relations(to_guid, rel);
"""


def server_tables():
    """Static tables of the private server; empty when the DB is missing."""
    out = collections.defaultdict(list)
    if not config.SERVER_DB.exists():
        print(f"warning: {config.SERVER_DB} not found, skipping server tables", file=sys.stderr)
        return out
    db = sqlite3.connect(f"file:{config.SERVER_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    for table in ("store_items", "pack_set_map", "chest_templates",
                  "equipment_card_variants", "conversation_rewards",
                  "tournament_types", "equipment_templates"):
        try:
            out[table] = [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
        except sqlite3.OperationalError as e:
            print(f"warning: {table}: {e}", file=sys.stderr)
    db.close()
    return out


def load_manifests():
    out = {}
    for group in ("cards", "portraits", "icons", "sleeves"):
        try:
            with open(config.ART / group / "manifest.json") as f:
                out[group] = set(json.load(f))
        except FileNotFoundError:
            print(f"warning: no {group} art, run python -m hexbrowser.extract_assets", file=sys.stderr)
            out[group] = set()
    return out


def art_ref(manifests, group, *names):
    for n in names:
        if n and n.lower() in manifests[group]:
            return f"{group}/{n.lower()}"
    return None


def build():
    gd, failed = load(config.GAMEDATA)
    srv = server_tables()
    art = load_manifests()

    # ---- sets
    sets = {}
    for s in gd["CardSetTemplate"]:
        kind, no = sources.classify_set(s["m_Name"])
        sets[guid(s["m_Id"])] = {
            "guid": guid(s["m_Id"]), "name": s["m_Name"], "set_no": no, "kind": kind,
            "release_date": s.get("m_ReleaseDate") or "", "bundle": s.get("m_BundleName")}

    # ---- server context
    store = {r["template_guid"]: r for r in srv["store_items"]}
    booster_sets = {sets[r["set_guid"]]["set_no"] for r in srv["pack_set_map"]
                    if r["set_guid"] in sets and r["pack_guid"] in store}
    chest_loot = {r["guid"] for r in srv["equipment_templates"] if r.get("is_chest_loot")}
    ctx = collections.defaultdict(list)       # guid -> extra sources from relations
    relations = []

    for r in srv["conversation_rewards"]:
        reward = json.loads(r["reward_json"] or "{}")
        for race, card in (reward.get("card_guid_by_race") or {}).items():
            ctx[card].append(sources.src("Campaign Reward", f"Campaign quest reward ({race})"))
        if reward.get("chest_guid"):
            ctx[reward["chest_guid"]].append(sources.src("Campaign Reward", "Campaign quest reward"))
    for t in srv["tournament_types"]:
        rewards = json.loads(t["rewards_json"] or "{}").get("tournamentRewards") or []
        for tier in rewards:
            for prize in tier.get("rewards") or []:
                g = guid(prize.get("prizeResource"))
                if g:
                    ctx[g].append(sources.src("Server Tournament", t["name"]))

    decks = {guid(d["m_Id"]): d for d in gd["DeckTemplate"]}
    mercs = {guid(m["m_Id"]): m for m in gd["MercenaryTemplate"]}

    items, item_sources = {}, {}

    # ---- inventory items
    for rec in gd["InventoryItemData"]:
        kind = ITEM_KINDS.get(short_type(rec))
        if not kind:
            continue
        g = guid(rec["m_Id"])
        set_guid = guid(rec.get("m_SetId")) or guid(rec.get("m_MercenarySet"))
        s = sets.get(set_guid, {})
        art_no = rec.get("m_ArtNumber") or ""
        extra = {"price": rec.get("m_BasePrice")}
        text, subtype, artist, image = rec.get("m_Description"), "", None, None

        if kind == "equipment":
            subtype = rec.get("m_EquipmentType")
            extra.update(modifiers=rec.get("m_Modifiers"), design_notes=rec.get("m_DesignNotes"))
            srcs = sources.text_sources(rec.get("m_DesignNotes"))
            if srcs[0]["category"] == "Unknown" and g in chest_loot:
                srcs = [sources.src("Treasure Chest", f"{sources.set_label(s.get('set_no'))} chests".strip())]
            elif srcs[0]["category"] == "Unknown" and s.get("name"):
                # no origin note: fall back to the equipment's set
                srcs = sources.text_sources(s["name"])
                if srcs[0]["category"] == "Unknown":
                    srcs = [sources.src("Unknown", f"{s['name']} equipment, origin not recorded")]
        elif kind == "mercenary":
            tmpl = mercs.get(guid(rec.get("m_MercenaryTemplateId"))) or {}
            text = tmpl.get("m_GameText") or ""
            subtype = tmpl.get("m_SubType") or ""
            artist = tmpl.get("m_ArtistName")
            extra.update(health=tmpl.get("m_StartingHealth"), race=tmpl.get("m_Race"),
                         gender=tmpl.get("m_Gender"), origin=rec.get("m_Description"))
            image = art_ref(art, "portraits", art_name(tmpl.get("m_HudPortrait")), art_no)
            srcs = sources.text_sources(rec.get("m_Description"))
            deck = decks.get(guid(rec.get("m_DeckTemplateId")))
            if deck:
                extra["deck"] = deck.get("m_DeckName")
        elif kind in ("sleeve", "gameboard", "coin"):
            text = rec.get("m_Reason") or ""
            if kind == "sleeve":
                image = art_ref(art, "sleeves", art_no, art_name(rec.get("m_ImagePath")))
            elif kind == "gameboard":
                image = art_ref(art, "icons", art_no)
            srcs = sources.text_sources(rec.get("m_Reason"))
        elif kind == "starter":
            deck = decks.get(guid(rec.get("m_DeckTemplateId")))
            subtype = rec.get("m_CardPackType") or ""
            if deck:
                for res in deck.get("m_DeckResources") or []:
                    card = guid(res.get("m_idTemplate"))
                    if card:
                        relations.append((card, "in_starter", g, res.get("m_Count", 1)))
            srcs = []
        elif kind == "pack":
            subtype = rec.get("m_CardPackType") or ""
            if set_guid:
                relations.append((g, "pack_of_set", set_guid, 1))
            srcs = []
        elif kind == "chest":
            subtype = rec.get("m_TreasureChestType") or ""
            extra["promotional_id"] = rec.get("m_PromotionalID")
            srcs = []
        else:
            subtype = rec.get("m_GemTypeNew") or rec.get("m_TicketType") or ""
            srcs = []
            if kind == "gem":
                color = next((t["m_ColorFlags"] for t in rec.get("m_Threshold") or []), None)
                major, minor = GEM_ART.get(color, GEM_ART[None])
                image = art_ref(art, "cards", minor if "Minor" in (rec.get("m_Name") or "") else major)
                srcs = [sources.src("Unknown", "PvE socket gem; the server code never grants gems as items")]

        if g in store:
            st = store[g]
            srcs = [sources.src("Store", f"{st['price']} {st['currency']} ({st['store_tab']})")] + \
                   [x for x in srcs if x["category"] not in ("Unknown", "Store")]
        srcs = ctx.get(g, []) + srcs
        if not srcs:
            srcs = sources.text_sources(rec.get("m_Name")) if kind in ("pack", "chest") else [sources.src("Unknown")]
            if kind == "pack" and srcs[0]["category"] == "Unknown":
                srcs = [sources.src("Unknown", "Not sold in the server store")]

        thr = {t["m_ColorFlags"]: t["m_ThresholdColorRequirement"] for t in rec.get("m_Threshold") or []}
        items[g] = {
            "guid": g, "kind": kind, "name": rec.get("m_Name"), "set_guid": set_guid,
            "set_name": s.get("name"), "set_no": s.get("set_no"), "set_kind": s.get("kind"),
            "rarity": rec.get("m_Rarity") or "", "type": kind.capitalize(), "subtype": subtype,
            "faction": None, "cost": None, "threshold_json": json.dumps(thr) if thr else None,
            "attack": None, "defense": None, "text": text, "flavor": None, "artist": artist,
            "art": art_no, "icon": art_ref(art, "icons", art_no) or (image if kind == "gem" else None), "image": image,
            "pve": int(bool(rec.get("m_IsPvE"))), "tradeable": int(bool(rec.get("m_Tradeable", 1))),
            "is_promo": int(bool(rec.get("m_IsPromo"))), "is_unique": 1, "max_copies": 1,
            "is_alternate": 0, "base_guid": None, "collectible": int(kind in COLLECTIBLE_KINDS),
            "extra_json": json.dumps({k: v for k, v in extra.items() if v not in (None, "")}),
        }
        item_sources[g] = srcs

    # ---- equipment -> card variants
    variant_cards = set()
    for r in srv["equipment_card_variants"]:
        variant_cards.add(r["variant_guid"])
        if r["equipment_key"] in items:
            relations.append((r["equipment_key"], "upgrades_card", r["base_guid"], 1))
            relations.append((r["variant_guid"], "variant_of", r["base_guid"], 1))

    # ---- cards
    starter_names = {g: i["name"] for g, i in items.items() if i["kind"] == "starter"}
    for card, rel, starter, qty in relations:
        if rel == "in_starter" and starter_names.get(starter):
            ctx[card].append(sources.src("Starter Deck", starter_names[starter]))
    cards = gd["CardTemplate"]
    loot = sources.server_loot()
    set_no_of = {g: s["set_no"] for g, s in sets.items()}
    base_by_name = {}
    for c in cards:
        s = sets.get(guid(c.get("m_SetId")), {})
        if s.get("kind") in ("main", "pve_promo", "campaign", "arena", "kickstarter", "holiday", "basic") \
                and c.get("m_CardRarity") != "Epic":
            base_by_name.setdefault(c.get("m_Name"), guid(c["m_Id"]))
    for c in cards:
        g = guid(c["m_Id"])
        s = sets.get(guid(c.get("m_SetId")), {})
        set_kind = "equipment_variant" if g in variant_cards else s.get("kind", "not_collectible")
        art_no = c.get("m_ArtNumber") or art_name(c.get("m_CardImagePath"))
        thr = {t["m_ColorFlags"]: t["m_ThresholdColorRequirement"] for t in c.get("m_Threshold") or []}
        rarity = c.get("m_CardRarity")
        # alternate-art printings: the *_alternates sets and the Epic (AA) cards of the main sets
        is_alt = set_kind == "alternate" or (set_kind == "main" and rarity == "Epic")
        unique = int(bool(c.get("m_Unique")))
        ref = art_ref(art, "cards", art_no)
        layout = c.get("m_DefaultLayout") or {}
        crop = [layout.get(k) for k in ("m_PortraitLeft", "m_PortraitTop", "m_PortraitRight", "m_PortraitBottom")]
        # portrait window of the 512² art as the game shows it: [left, top, right, bottom], 0..1
        valid_crop = None not in crop and crop[2] > crop[0] and crop[3] > crop[1]
        items[g] = {
            "guid": g, "kind": "card", "name": c.get("m_Name"), "set_guid": s.get("guid"),
            "set_name": s.get("name"), "set_no": s.get("set_no"), "set_kind": set_kind,
            "rarity": rarity, "type": c.get("m_CardType"),
            "subtype": c.get("m_CardSubtype"), "faction": c.get("m_Faction"),
            "cost": c.get("m_ResourceCost"), "threshold_json": json.dumps(thr) if thr else None,
            "attack": c.get("m_BaseAttackValue"), "defense": c.get("m_BaseDefenseValue"),
            "text": c.get("m_GameText"), "flavor": c.get("m_FlavorText"),
            "artist": c.get("m_ArtistName"), "art": art_no, "icon": ref, "image": ref,
            "pve": int(bool(c.get("m_IsPvE"))), "tradeable": int(bool(c.get("m_Tradeable"))),
            "art_crop": json.dumps([round(v, 4) for v in crop]) if valid_crop else None,
            "is_promo": 0, "is_unique": unique, "max_copies": 1 if unique else 4,
            "is_alternate": int(is_alt),
            "base_guid": base_by_name.get(c.get("m_Name")) if is_alt else None,
            "collectible": int(set_kind not in ("not_collectible", "equipment_variant")
                               and not (rarity == "Land" and set_kind != "basic")),
            "extra_json": json.dumps({k: v for k, v in {
                "number": c.get("m_CardNumber"), "sockets": c.get("m_SocketCount"),
                "attributes": c.get("m_AttributeFlags"),
                "extended_art": c.get("m_HasExtendedArt"),
            }.items() if v}),
        }
        srcs = sources.card_sources(
            {"name": c.get("m_Name"), "rarity": rarity, "set_guid": s.get("guid")},
            {"kind": set_kind, "set_no": s.get("set_no"), "name": s.get("name") or ""},
            ctx.get(g, []), booster_sets, loot, set_no_of)
        if g in store:
            st = store[g]
            srcs.insert(0, sources.src("Store", f"{st['price']} {st['currency']}"))
        if not items[g]["collectible"]:
            srcs = [x for x in srcs if x["category"] == "Not Collectible"] or \
                   [sources.src("Not Collectible", s.get("name") or "")]
        item_sources[g] = srcs

    n_over = sources.apply_overrides(item_sources, config.OVERRIDES)

    # ---- overall obtainability: best of all sources
    rank = {"yes": 0, "unknown": 1, "no": 2}
    for g, i in items.items():
        srcs = list({(x["category"], x["detail"]): x for x in item_sources.get(g, [])}.values())
        item_sources[g] = srcs
        i["obtainable"] = min((x["obtainable"] for x in srcs), key=rank.get, default="unknown")

    write(sets, items, item_sources, relations)
    report(items, item_sources, failed, n_over)


def write(sets, items, item_sources, relations):
    config.CACHE.mkdir(parents=True, exist_ok=True)
    tmp = config.CATALOG.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    cols = ["guid", "name", "set_no", "kind", "release_date", "bundle"]
    db.executemany(f"INSERT INTO sets VALUES ({','.join('?' * len(cols))})",
                   [[s[c] for c in cols] for s in sets.values()])
    icols = [r[1] for r in db.execute("PRAGMA table_info(items)")]
    db.executemany(f"INSERT INTO items VALUES ({','.join('?' * len(icols))})",
                   [[i.get(c) for c in icols] for i in items.values()])
    db.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?)",
                   [(g, x["category"], x["detail"], x["raw"], x["set_no"], x["obtainable"])
                    for g, lst in item_sources.items() for x in lst])
    db.executemany("INSERT INTO relations VALUES (?,?,?,?)", relations)
    db.commit()
    db.close()
    tmp.replace(config.CATALOG)


def report(items, item_sources, failed, n_over):
    print(f"catalog -> {config.CATALOG}")
    if failed:
        print(f"unparsable gamedata records: {failed}")
    if n_over:
        print(f"overrides applied: {n_over}")
    by_kind = collections.defaultdict(collections.Counter)
    for i in items.values():
        k = by_kind[i["kind"]]
        k["total"] += 1
        k["collectible"] += i["collectible"]
        k["icon"] += bool(i["icon"])
        k["unknown"] += all(x["category"] == "Unknown" for x in item_sources[i["guid"]])
        k[f"obt:{i['obtainable']}"] += i["collectible"]
    print(f"{'kind':10} {'total':>6} {'collect':>7} {'icon':>6} {'unknown':>7}  obtainable(yes/unknown/no, collectible only)")
    for kind, c in sorted(by_kind.items(), key=lambda kv: -kv[1]["total"]):
        print(f"{kind:10} {c['total']:6} {c['collectible']:7} {c['icon']:6} {c['unknown']:7}  "
              f"{c['obt:yes']}/{c['obt:unknown']}/{c['obt:no']}")
    cats = collections.Counter(x["category"] for g, lst in item_sources.items()
                               if items[g]["collectible"] for x in lst)
    print("sources (collectible items):", ", ".join(f"{k} {v}" for k, v in cats.most_common()))


if __name__ == "__main__":
    build()
