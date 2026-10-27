"""Read-only access to player data in the private server's hconnect.db.

The DB is opened with mode=ro, so it can be read while the server runs
(WAL mode keeps readers consistent). Card ownership is counted from
card_instances, which is what the server pushes to the client at login;
the collections table is only compared against it (see discrepancies).
User ids are 64-bit and are passed around as strings for the browser.
"""
import json
import sqlite3
from contextlib import contextmanager

from . import config
from .gamedata import NULL_GUID


def _guid(value):
    """Empty and all-zero GUIDs mean "default" (nothing chosen)."""
    return value if value and value != NULL_GUID else None


@contextmanager
def connect():
    db = sqlite3.connect(f"file:{config.SERVER_DB}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def list_accounts():
    with connect() as db:
        users = db.execute(
            "SELECT id, name, gold, platinum, level, experience, last_login, created_at "
            "FROM users ORDER BY name").fetchall()
        out = []
        for u in users:
            champs = db.execute(
                "SELECT champion_name, level, xp, is_deleted FROM champions "
                "WHERE user_id=? ORDER BY id", (u["id"],)).fetchall()
            cards = db.execute(
                "SELECT COUNT(DISTINCT template_guid), COUNT(*) FROM card_instances "
                "WHERE user_id=?", (u["id"],)).fetchone()
            out.append({
                "id": str(u["id"]), "name": u["name"], "gold": u["gold"],
                "platinum": u["platinum"], "level": u["level"],
                "experience": u["experience"], "last_login": u["last_login"],
                "created_at": u["created_at"],
                "distinct_cards": cards[0], "card_copies": cards[1],
                "champions": [{"name": c["champion_name"], "level": c["level"],
                               "xp": c["xp"], "deleted": bool(c["is_deleted"])}
                              for c in champs],
            })
        return out


def get_account(user_id):
    return next((a for a in list_accounts() if a["id"] == str(user_id)), None)


def resolve(id_or_name):
    """User id (as string) for a numeric id or a login name, else None."""
    with connect() as db:
        row = db.execute("SELECT id FROM users WHERE name = ?", (id_or_name,)).fetchone()
        if row is None and id_or_name.isdigit():
            row = db.execute("SELECT id FROM users WHERE id = ?", (int(id_or_name),)).fetchone()
    return str(row[0]) if row else None


def ownership(user_id):
    """{template guid: {"qty": copies, "ext": extended-art copies}} for cards and items."""
    uid = int(user_id)
    owned = {}
    with connect() as db:
        for r in db.execute(
                "SELECT template_guid, COUNT(*) AS qty, SUM(is_extended_art) AS ext "
                "FROM card_instances WHERE user_id=? GROUP BY template_guid", (uid,)):
            owned[r["template_guid"]] = {"qty": r["qty"], "ext": r["ext"] or 0}
        for r in db.execute(
                "SELECT template_guid, SUM(quantity) AS qty FROM player_inventory "
                "WHERE user_id=? GROUP BY template_guid", (uid,)):
            if r["qty"] > 0:
                owned.setdefault(r["template_guid"], {"qty": 0, "ext": 0})["qty"] += r["qty"]
    return owned


def stardust(user_id):
    with connect() as db:
        return {r["rarity"]: r["quantity"] for r in db.execute(
            "SELECT rarity, quantity FROM stardust WHERE user_id=?", (int(user_id),))}


def discrepancies(user_id):
    """Cards whose collections.quantity differs from the number of card_instances."""
    with connect() as db:
        rows = db.execute(
            "SELECT c.card_template_id AS guid, c.quantity AS collection_qty, "
            "(SELECT COUNT(*) FROM card_instances i WHERE i.user_id=c.user_id "
            " AND i.template_guid=c.card_template_id) AS instance_qty "
            "FROM collections c WHERE c.user_id=?", (int(user_id),)).fetchall()
    return [dict(r) for r in rows if r["collection_qty"] != r["instance_qty"]]


def decks(user_id):
    """Decks with resolved cards; deck.cards holds card GUIDs or instance ids."""
    uid = int(user_id)
    with connect() as db:
        instances = {r[0]: r[1] for r in db.execute(
            "SELECT instance_id, template_guid FROM card_instances WHERE user_id=?", (uid,))}
        rows = db.execute(
            "SELECT id, deck_name, cards, pvp_champion_guid, pve_champion_id, "
            "deck_sleeve_guid, gameboard_guid, coin_guid, equipment, last_saved "
            "FROM decks WHERE user_id=? ORDER BY last_saved DESC, id", (uid,)).fetchall()
    out = []
    for d in rows:
        counts, unresolved = {}, 0
        for entry in json.loads(d["cards"] or "[]"):
            g = instances.get(entry) if isinstance(entry, int) else entry
            if g:
                counts[g] = counts.get(g, 0) + 1
            else:
                unresolved += 1
        try:
            equipment = json.loads(d["equipment"] or "[]")
        except json.JSONDecodeError:
            equipment = []
        out.append({
            "id": d["id"], "name": d["deck_name"], "last_saved": d["last_saved"],
            "cards": [{"guid": g, "qty": n} for g, n in counts.items()],
            "card_count": sum(counts.values()), "unresolved": unresolved,
            "pvp_champion": _guid(d["pvp_champion_guid"]), "pve_champion_id": d["pve_champion_id"],
            "sleeve": _guid(d["deck_sleeve_guid"]), "gameboard": _guid(d["gameboard_guid"]),
            "coin": _guid(d["coin_guid"]), "equipment": equipment,
        })
    return out
