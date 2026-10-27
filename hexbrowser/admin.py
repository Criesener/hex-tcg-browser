"""Optional admin mode: grant cards and items to an account in the server DB.

Only active when the browser runs with ./run.sh --admin (HEXBROWSER_ADMIN=1);
otherwise server.py registers no write endpoint at all. A grant

  1. is refused while the hex-server runs: it keeps profiles in memory and
     pushes card instances to the client at login, so a change made under it
     would be raced or overwritten;
  2. backs up hconnect.db to server-state/hconnect.db.browser-<time>.bak;
  3. writes through the hex-server's own profile_db helpers, exactly as
     new_player.py grants the starting collection (collections + one
     card_instances row per copy; inventory items via player_inventory),
     in a single transaction.
"""
import datetime
import json
import os
import socket
import sqlite3
import subprocess
import sys
import types

from . import config

ENABLED = os.environ.get("HEXBROWSER_ADMIN") == "1"
CONTAINER = os.environ.get("HEX_SERVER_CONTAINER", "hex-server")
GAME_PORT = 9933
# Non-card kinds the server keeps in player_inventory.
INVENTORY_KINDS = {"equipment", "mercenary", "sleeve", "gameboard", "coin", "gem",
                   "pack", "starter", "chest"}
LOG = config.CACHE / "admin.log"


class AdminError(Exception):
    pass


def server_running():
    """Why the hex-server counts as running, or None if it is stopped."""
    try:
        out = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
                             capture_output=True, text=True, timeout=5)
        if out.stdout.strip() == "true":
            return f"docker container '{CONTAINER}' is running"
    except (OSError, subprocess.TimeoutExpired):
        pass   # no docker: rely on the port check
    try:
        with socket.create_connection(("127.0.0.1", GAME_PORT), timeout=0.5):
            return f"port {GAME_PORT} is open"
    except OSError:
        return None


def _profile_db():
    """Import hex-server's profile_db without its db module: importing db opens
    and seeds a database at import time. The grant helpers only touch the
    connection they are given, so an empty stand-in is enough."""
    sys.modules.setdefault("db", types.ModuleType("db"))
    sys.modules["db"].__dict__.setdefault("_db", None)
    if str(config.HEX_SERVER_SRC) not in sys.path:
        sys.path.append(str(config.HEX_SERVER_SRC))
    import profile_db
    return profile_db


def backup():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = config.SERVER_DB.with_name(f"{config.SERVER_DB.name}.browser-{stamp}.bak")
    src = sqlite3.connect(f"file:{config.SERVER_DB}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)   # consistent copy including the WAL
    finally:
        out.close()
        src.close()
    return dst


def grant(user_id, entries, check_server=True):
    """entries: [(guid, kind, qty)]. Returns {"backup": path, "cards": n, "items": n}."""
    entries = [(g, k, int(q)) for g, k, q in entries if int(q) > 0]
    if not entries:
        raise AdminError("nothing to grant")
    for g, k, _ in entries:
        if k != "card" and k not in INVENTORY_KINDS:
            raise AdminError(f"{k} items cannot be granted ({g})")
    if check_server:
        reason = server_running()
        if reason:
            raise AdminError(f"Stop the hex-server first ({reason}): ./server/hex-server.sh stop")
    pdb = _profile_db()
    bak = backup()
    conn = sqlite3.connect(config.SERVER_DB, timeout=5, isolation_level=None)
    cards = items = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        cid = pdb.db_next_card_instance_id(user_id, conn=conn)
        for g, kind, qty in entries:
            if kind == "card":
                pdb.db_grant_collection_cards(user_id, g, qty, conn=conn)
                cid = pdb.db_insert_collection_card_instances(user_id, cid, g, qty, conn=conn)
                cards += qty
            else:
                pdb.db_grant_inventory_item(user_id, g, qty, conn=conn)
                items += qty
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    with open(LOG, "a") as f:
        f.write(json.dumps({"time": datetime.datetime.now().isoformat(timespec="seconds"),
                            "user_id": str(user_id), "backup": bak.name,
                            "entries": entries}) + "\n")
    return {"backup": str(bak), "cards": cards, "items": items}
