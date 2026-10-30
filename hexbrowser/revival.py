"""Read-only access to the save files of the HEX Revival mod.

HEX Revival keeps one folder per offline account in HexRevivalSaves/ and the
online account in HexRevivalOnline/ (next to it):
  account.txt      key=value lines: unlock (1 = everything unlocked), gold, ...
  collection.txt   "<card guid> <copies>" per line (missing when unlock=1)
  inventory.txt    "<item guid> <count>": equipment, sleeves, packs, stardust
  chests.txt       treasure chests by set (not catalog items, not shown)
  champions.txt    id|name|level|class|race|gender|...
  decks.txt        blocks of DECK|id|name|.. CARDS|guid,.. SIDE| EQUIP| TALENT|
online_profile.json holds the community-server login and is never read.

config.REVIVAL_SAVES may list several game installs. Accounts get ids
"rev:<install>:<folder>" (install = the folder holding Hex.app), the online
account "rev:<install>:online", so account.py can tell them from server
accounts (numeric ids). Files are read on every call.

grant() (admin mode) adds cards to collection.txt and items to inventory.txt.
It is refused while HEX runs from the same install, because the game keeps the
account in memory and would overwrite the files on its next save. Both files
are backed up to cache/revival-backups/ first.
"""
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone

from . import config
from .gamedata import NULL_GUID

# Item kinds the mod keeps in inventory.txt (seen in its save files).
GRANT_KINDS = {"equipment", "sleeve", "mercenary", "pack"}
PREFIX = "rev:"
ONLINE = "online"
_EPOCH_TICKS = 621355968000000000   # .NET ticks at 1970-01-01


def is_revival(account_id):
    return str(account_id).startswith(PREFIX)


def _installs():
    return [s for s in config.REVIVAL_SAVES if s.is_dir()]


def _folders():
    """{account id: (folder, install dir, online?)} of all accounts with an account.txt."""
    out = {}
    for saves in _installs():
        install = saves.parent
        for d in sorted(saves.iterdir()):
            if (d / "account.txt").is_file():
                out[f"{PREFIX}{install.name}:{d.name}"] = (d, install, False)
        online = install / "HexRevivalOnline"
        if (online / "account.txt").is_file():
            out[f"{PREFIX}{install.name}:{ONLINE}"] = (online, install, True)
    return out


def _folder(account_id):
    entry = _folders().get(account_id)
    return entry[0] if entry else None


def _lines(path):
    try:
        return [l.strip() for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    except FileNotFoundError:
        return []


def _counts(path):
    """{guid: count} of a "<guid> <count>" file."""
    out = {}
    for l in _lines(path):
        guid, _, qty = l.partition(" ")
        n = _int(qty.strip())
        if n > 0:
            out[guid] = out.get(guid, 0) + n
    return out


def _settings(folder):
    return dict(l.split("=", 1) for l in _lines(folder / "account.txt") if "=" in l)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ticks(value):
    t = _int(value)
    if t <= _EPOCH_TICKS:
        return None
    return datetime.fromtimestamp((t - _EPOCH_TICKS) / 1e7, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _guid(value):
    return value if value and value != NULL_GUID else None


def _catalog():
    return sqlite3.connect(f"file:{config.CATALOG}?mode=ro", uri=True)


def _unlocked(kind):
    """{guid: copies} an unlock=1 account owns of kind: every collectible card
    as a playset, every piece of equipment once."""
    db = _catalog()
    try:
        return dict(db.execute(
            "SELECT guid, max_copies FROM items WHERE kind = ? AND (collectible = 1 OR kind != 'card')",
            (kind,)))
    finally:
        db.close()


def _cards(folder):
    if _settings(folder).get("unlock") == "1":
        return _unlocked("card")
    return _counts(folder / "collection.txt")


def _champions(folder):
    out = []
    for l in _lines(folder / "champions.txt"):
        f = l.split("|")
        if len(f) > 2:
            out.append({"name": f[1], "level": _int(f[2], 1), "xp": 0, "deleted": False})
    return out


def list_accounts():
    several = len(_installs()) > 1
    out = []
    for aid, (folder, install, online) in _folders().items():
        s = _settings(folder)
        cards = _cards(folder)
        name = folder.name
        if online:
            champ = next(iter(_champions(folder)), None)
            name = f"{champ['name'] if champ else 'Online account'} (online)"
        out.append({
            "id": aid, "name": f"{name} · {install.name}" if several else name,
            "source": "revival", "install": install.name,
            "gold": _int(s.get("gold")), "platinum": _int(s.get("platinum")),
            "level": _int(s.get("level"), 1), "experience": _int(s.get("xp")),
            "last_login": _ticks(s.get("lastplayed")), "created_at": None,
            "unlock_all": s.get("unlock") == "1",
            "distinct_cards": len(cards), "card_copies": sum(cards.values()),
            "champions": _champions(folder),
        })
    return out


def resolve(id_or_name):
    """Account id for "rev:<install>:<folder>", or a folder name that is unique."""
    folders = _folders()
    if id_or_name in folders:
        return id_or_name
    matches = [aid for aid in folders if aid.rsplit(":", 1)[-1] == id_or_name]
    return matches[0] if len(matches) == 1 else None


def ownership(account_id):
    """{guid: {"qty", "ext"}} from collection.txt (cards) and inventory.txt (items)."""
    folder = _folder(account_id)
    if folder is None:
        return {}
    items = _counts(folder / "inventory.txt")
    if _settings(folder).get("unlock") == "1":
        items = {**_unlocked("equipment"), **items}
    owned = {g: {"qty": n, "ext": 0} for g, n in _cards(folder).items()}
    for g, n in items.items():
        owned.setdefault(g, {"qty": 0, "ext": 0})["qty"] += n
    return owned


def stardust(account_id):
    """{rarity: count} from the stardust items in inventory.txt."""
    folder = _folder(account_id)
    if folder is None:
        return {}
    counts = _counts(folder / "inventory.txt")
    if not counts:
        return {}
    db = _catalog()
    try:
        names = dict(db.execute(
            f"SELECT guid, name FROM items WHERE kind = 'stardust' AND guid IN ({','.join('?' * len(counts))})",
            list(counts)))
    finally:
        db.close()
    return {names[g].removesuffix(" Stardust"): n for g, n in counts.items() if g in names}


def decks(account_id):
    folder = _folder(account_id)
    if folder is None:
        return []
    out = []
    for l in _lines(folder / "decks.txt"):
        tag, _, rest = l.partition("|")
        if tag == "DECK":
            f = rest.split("|")
            f += [""] * (7 - len(f))
            out.append({
                "id": _int(f[0]), "name": f[1], "last_saved": None,
                "cards": [], "card_count": 0, "unresolved": 0,
                "pvp_champion": _guid(f[3]), "pve_champion_id": None,
                "sleeve": _guid(f[4]), "gameboard": _guid(f[5]), "coin": _guid(f[6]),
                "equipment": [],
            })
        elif out and tag in ("CARDS", "EQUIP"):
            guids = [g for g in rest.replace("|", ",").split(",") if _guid(g)]
            if tag == "EQUIP":
                out[-1]["equipment"] = guids
                continue
            counts = {}
            for g in guids:
                counts[g] = counts.get(g, 0) + 1
            out[-1]["cards"] = [{"guid": g, "qty": n} for g, n in counts.items()]
            out[-1]["card_count"] = len(guids)
    return out


# ------------------------------------------------------------------ admin

class GrantError(Exception):
    pass


def game_running(account_id):
    """Why HEX counts as running for this account's install, or None."""
    entry = _folders().get(account_id)
    if entry is None:
        return None
    exe = f"{entry[1]}/Hex.app/"
    try:
        out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.stdout.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if cmd.startswith(exe):
            return f"HEX is running from {entry[1].name} (pid {pid})"
    return None


def _backup(account_id, folder):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = config.CACHE / "revival-backups" / account_id[len(PREFIX):].replace(":", "/") / stamp
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("collection.txt", "inventory.txt"):
        if (folder / name).is_file():
            shutil.copy2(folder / name, dst / name)
    return dst


def _add_counts(path, add):
    """Add {guid: n} to a "<guid> <count>" file, keeping its order; new guids go last."""
    lines, seen = [], set()
    for l in _lines(path):
        guid, _, qty = l.partition(" ")
        if guid in add and guid not in seen:
            l = f"{guid} {_int(qty.strip()) + add[guid]}"
            seen.add(guid)
        lines.append(l)
    lines += [f"{g} {n}" for g, n in add.items() if g not in seen]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    os.replace(tmp, path)


def grant(account_id, entries, check_game=True):
    """entries: [(guid, kind, qty)]. Returns {"backup": path, "cards": n, "items": n}."""
    folder = _folder(account_id)
    if folder is None:
        raise GrantError(f"unknown account {account_id}")
    if _settings(folder).get("unlock") == "1":
        raise GrantError("this account has everything unlocked")
    entries = [(g, k, int(q)) for g, k, q in entries if int(q) > 0]
    if not entries:
        raise GrantError("nothing to grant")
    for g, k, _ in entries:
        if k != "card" and k not in GRANT_KINDS:
            raise GrantError(f"{k} items cannot be granted to HEX Revival accounts ({g})")
    if check_game:
        reason = game_running(account_id)
        if reason:
            raise GrantError(f"Quit HEX first ({reason})")
    cards, items = {}, {}
    for g, k, q in entries:
        target = cards if k == "card" else items
        target[g] = target.get(g, 0) + q
    bak = _backup(account_id, folder)
    if cards:
        _add_counts(folder / "collection.txt", cards)
    if items:
        _add_counts(folder / "inventory.txt", items)
    with open(config.CACHE / "admin.log", "a") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                            "account": account_id, "backup": str(bak),
                            "entries": entries}) + "\n")
    return {"backup": str(bak), "cards": sum(cards.values()), "items": sum(items.values())}
