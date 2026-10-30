"""HexTcgBrowser web app: JSON API over catalog.sqlite plus live account data.

Run: .venv/bin/uvicorn hexbrowser.server:app --host 127.0.0.1 --port 8090
(or ./run.sh). Nothing here writes to the server DB, except the grant
endpoint that only exists in admin mode (./run.sh --admin, see admin.py).
"""
import collections
import csv as csvlib
import inspect
import io
import json
import re
import sqlite3
import threading

from fastapi import Body, Depends, FastAPI, HTTPException, Path, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import account, admin, config, revival, thumbs

app = FastAPI(title="HexTcgBrowser")

ACCOUNT_DOC = "Account id or login name, e.g. player@example.com"

RARITY_ORDER = ["Land", "Common", "Uncommon", "Rare", "Epic", "Legendary", "Promo"]
SHARDS = ["Blood", "Diamond", "Ruby", "Sapphire", "Wild"]
LIST_COLUMNS = ("guid, kind, name, set_name, set_no, set_kind, rarity, type, subtype, "
                "faction, cost, threshold_json, attack, defense, icon, pve, is_alternate, "
                "max_copies, collectible, obtainable, art_crop, is_unique, text, extra_json")
SORTS = {
    "name": "name COLLATE NOCASE, set_no",
    "cost": "cost IS NULL, cost, name COLLATE NOCASE",
    "set": ("set_no IS NULL, set_no, CASE set_kind WHEN 'basic' THEN 0 WHEN 'main' THEN 1 "
            "WHEN 'pve_promo' THEN 2 WHEN 'campaign' THEN 3 WHEN 'arena' THEN 4 ELSE 9 END, "
            "set_name, is_alternate, json_extract(extra_json, '$.number'), name COLLATE NOCASE"),
    "rarity": ("CASE rarity " + " ".join(f"WHEN '{r}' THEN {i}" for i, r in enumerate(RARITY_ORDER))
               + " ELSE 99 END DESC, name COLLATE NOCASE"),
}

_local = threading.local()


def catalog():
    """One read-only connection per worker thread, reopened after a rebuild."""
    try:
        mtime = config.CATALOG.stat().st_mtime
    except FileNotFoundError:
        raise HTTPException(503, "catalog missing: run python -m hexbrowser.build_catalog")
    db = getattr(_local, "db", None)
    if db is None or _local.mtime != mtime:
        if db is not None:
            db.close()
        db = sqlite3.connect(f"file:{config.CATALOG}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        _local.db, _local.mtime = db, mtime
    return db


def row_out(r):
    d = dict(r)
    if "threshold_json" in d:
        d["threshold"] = json.loads(d.pop("threshold_json") or "{}")
    if "extra_json" in d:
        d["extra"] = json.loads(d.pop("extra_json") or "{}")
    if d.get("art_crop"):
        d["art_crop"] = json.loads(d["art_crop"])
    return d


def user_or_404(account_id):
    """Accounts are addressed by numeric id or login name."""
    uid = account.resolve(account_id)
    if uid is None:
        raise HTTPException(404, f"account not found: {account_id}")
    return uid


def owned_or_404(account_id):
    if not account_id:
        return None
    return account.ownership(user_or_404(account_id))


def csv(value):
    return [v for v in (value or "").split(",") if v]


# ------------------------------------------------------------------ meta

@app.get("/api/meta")
def meta():
    db = catalog()
    kinds = [dict(r) for r in db.execute(
        "SELECT kind, COUNT(*) AS total, SUM(collectible) AS collectible FROM items "
        "GROUP BY kind ORDER BY total DESC")]
    sets = [dict(r) for r in db.execute(
        "SELECT set_name AS name, set_no, set_kind, kind, COUNT(*) AS total FROM items "
        "WHERE set_name IS NOT NULL GROUP BY set_name, kind ORDER BY set_no IS NULL, set_no, set_name")]

    def distinct(col, kind=None):
        sql = f"SELECT DISTINCT {col} FROM items WHERE {col} IS NOT NULL AND {col} != ''"
        args = ()
        if kind:
            sql += " AND kind=?"
            args = (kind,)
        return sorted(r[0] for r in db.execute(sql, args))

    card_types = sorted({t for v in distinct("type", "card") for t in v.split("|")})
    rarities = [r for r in RARITY_ORDER if r in set(distinct("rarity"))]
    categories = [dict(r) for r in db.execute(
        "SELECT category, obtainable, COUNT(DISTINCT item_guid) AS items FROM sources "
        "GROUP BY category ORDER BY items DESC")]
    return {
        "kinds": kinds, "sets": sets, "rarities": rarities, "card_types": card_types,
        "factions": distinct("faction", "card"), "shards": SHARDS,
        "equipment_slots": distinct("subtype", "equipment"),
        "source_categories": categories, "sorts": list(SORTS),
        "admin": admin.ENABLED,
        "frame": frame_layout(),
    }


def frame_layout():
    """Boxes of the in-game card frame sprites (extract_assets frame), or None."""
    try:
        return json.loads((config.ART / "frame" / "layout.json").read_text())
    except FileNotFoundError:
        return None


# ------------------------------------------------------------------ items

def item_filters(
    kind: str = Query("card", description="Item kind(s), comma separated; empty for all"),
    q: str = "", text: bool = False,
    set: str = "", rarity: str = "", type: str = "", faction: str = "", subtype: str = "",
    cost: str = "", shard: str = "", attack: str = "", defense: str = "",
    source: str = "", obtainable: str = "",
    pve: int | None = None, alternates: bool = True, all: bool = False,
    owned: str = "", account_id: str = Query("", alias="account", description=ACCOUNT_DOC),
    sort: str = "set",
):
    return dict(locals())


# plain defaults of item_filters (Query(...) defaults unwrapped), for internal queries
FILTER_DEFAULTS = {n: getattr(p.default, "default", p.default)
                   for n, p in inspect.signature(item_filters).parameters.items()}


def query_items(f, columns=LIST_COLUMNS):
    """All items matching the filters (owned counts added when an account is given)."""
    where, args = [], []
    if not f["all"]:
        where.append("collectible = 1")
    if f["q"]:
        cols = "(name LIKE ? OR text LIKE ? OR subtype LIKE ?)" if f["text"] else "name LIKE ?"
        where.append(cols)
        args += [f"%{f['q']}%"] * (3 if f["text"] else 1)

    def any_of(column, values, like=False):
        if values:
            op = "LIKE" if like else "="
            where.append("(" + " OR ".join(f"{column} {op} ?" for _ in values) + ")")
            args.extend(f"%{v}%" if like else v for v in values)

    any_of("kind", csv(f["kind"]))
    any_of("set_name", csv(f["set"]))
    any_of("rarity", csv(f["rarity"]))
    any_of("type", csv(f["type"]), like=True)
    any_of("faction", csv(f["faction"]))
    any_of("subtype", csv(f["subtype"]))
    any_of("obtainable", csv(f["obtainable"]))
    for column in ("cost", "attack", "defense"):
        value = f[column]
        if value:
            if value.endswith("+"):
                where.append(f"{column} >= ?")
                args.append(int(value[:-1]))
            else:
                where.append(f"{column} = ?")
                args.append(int(value))
    for s in csv(f["shard"]):
        if s == "Colorless":
            where.append("(threshold_json IS NULL OR threshold_json = '{}')")
        else:
            where.append("json_extract(threshold_json, ?) IS NOT NULL")
            args.append(f'$."{s}"')
    if f["source"]:
        cats = csv(f["source"])
        where.append(f"guid IN (SELECT item_guid FROM sources WHERE category IN ({','.join('?' * len(cats))}))")
        args += cats
    if f["pve"] is not None:
        where.append("pve = ?")
        args.append(f["pve"])
    if not f["alternates"]:
        where.append("is_alternate = 0")

    order = SORTS.get(f["sort"], SORTS["set"])
    rows = catalog().execute(
        f"SELECT {columns} FROM items WHERE {' AND '.join(where) or '1'} ORDER BY {order}", args
    ).fetchall()

    own = owned_or_404(f["account_id"])
    owned = f["owned"]
    result = []
    for r in rows:
        d = row_out(r)
        if own is not None:
            d["owned"] = own.get(d["guid"], {}).get("qty", 0)
            if owned == "owned" and d["owned"] == 0:
                continue
            if owned == "missing" and d["owned"] > 0:
                continue
            if owned == "incomplete" and d["owned"] >= d["max_copies"]:
                continue
        result.append(d)
    return result


@app.get("/api/items")
def items(f: dict = Depends(item_filters), page: int = 1, page_size: int = Query(60, le=500)):
    result = query_items(f)
    start = (max(page, 1) - 1) * page_size
    return {"total": len(result), "page": page, "page_size": page_size,
            "items": result[start:start + page_size]}


@app.get("/api/items.csv")
def items_csv(f: dict = Depends(item_filters)):
    """The filtered list as CSV, e.g. ?kind=&owned=missing&account=... for a missing list."""
    result = query_items(f)
    cats = collections.defaultdict(list)
    for s in catalog().execute("SELECT item_guid, category, detail FROM sources"):
        cats[s[0]].append(s[1] + (f" ({s[2]})" if s[2] else ""))
    out = io.StringIO()
    w = csvlib.writer(out)
    has_owned = bool(f["account_id"])
    w.writerow(["name", "kind", "set", "set_no", "rarity", "type", "subtype", "obtainable", "sources"]
               + (["owned", "max_copies", "missing"] if has_owned else []) + ["guid"])
    for d in result:
        w.writerow([d["name"], d["kind"], d["set_name"], d["set_no"], d["rarity"], d["type"],
                    d["subtype"], d["obtainable"], "; ".join(cats[d["guid"]])]
                   + ([d["owned"], d["max_copies"], max(0, d["max_copies"] - d["owned"])]
                      if has_owned else []) + [d["guid"]])
    name = "hex-" + "-".join(x for x in (f["owned"] or "items", f["kind"] or "all", f["set"]) if x)
    name = re.sub(r"[^\w.-]+", "_", name)[:80] + ".csv"
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/items/{guid}")
def item(guid: str, account_id: str = Query("", alias="account", description=ACCOUNT_DOC)):
    db = catalog()
    r = db.execute("SELECT * FROM items WHERE guid = ?", (guid,)).fetchone()
    if r is None:
        raise HTTPException(404, "item not found")
    d = row_out(r)
    d["sources"] = [dict(s) for s in db.execute(
        "SELECT category, detail, raw_text, obtainable FROM sources WHERE item_guid = ?", (guid,))]

    def linked(sql, *a):
        return [row_out(x) for x in db.execute(sql, a)]

    brief = "i.guid, i.kind, i.name, i.set_name, i.rarity, i.icon, i.max_copies"
    rel = {
        "in_starters": linked(f"SELECT {brief}, r.qty FROM relations r JOIN items i ON i.guid = r.to_guid "
                              "WHERE r.from_guid = ? AND r.rel = 'in_starter'", guid),
        "starter_cards": linked(f"SELECT {brief}, r.qty FROM relations r JOIN items i ON i.guid = r.from_guid "
                                "WHERE r.to_guid = ? AND r.rel = 'in_starter' ORDER BY i.name", guid),
        "upgrades_cards": linked(f"SELECT {brief} FROM relations r JOIN items i ON i.guid = r.to_guid "
                                 "WHERE r.from_guid = ? AND r.rel = 'upgrades_card'", guid),
        "upgraded_by": linked(f"SELECT {brief}, i.subtype FROM relations r JOIN items i ON i.guid = r.from_guid "
                              "WHERE r.to_guid = ? AND r.rel = 'upgrades_card' ORDER BY i.name", guid),
        "variant_of": linked(f"SELECT {brief} FROM relations r JOIN items i ON i.guid = r.to_guid "
                             "WHERE r.from_guid = ? AND r.rel = 'variant_of'", guid),
    }
    if d["kind"] == "card":
        base = d["base_guid"] or guid
        rel["versions"] = linked(
            f"SELECT {brief}, i.is_alternate FROM items i WHERE i.kind = 'card' AND i.guid != ? "
            "AND (i.guid = ? OR i.base_guid = ?) ORDER BY i.is_alternate, i.set_no", guid, base, base)
    d["relations"] = {k: v for k, v in rel.items() if v}

    own = owned_or_404(account_id)
    if own is not None:
        d["owned"] = own.get(guid, {"qty": 0, "ext": 0})
        for lst in d["relations"].values():
            for x in lst:
                x["owned"] = own.get(x["guid"], {}).get("qty", 0)
    return d


# ------------------------------------------------------------------ accounts

@app.get("/api/accounts")
def accounts():
    return account.list_accounts()


@app.get("/api/accounts/{account_id}/summary")
def summary(account_id: str = Path(description=ACCOUNT_DOC)):
    uid = user_or_404(account_id)
    own = account.ownership(uid)
    db = catalog()
    rows = db.execute(
        "SELECT guid, kind, set_name, set_no, set_kind, max_copies, obtainable FROM items "
        "WHERE collectible = 1").fetchall()
    cats = collections.defaultdict(list)
    for s in db.execute("SELECT item_guid, category FROM sources"):
        cats[s[0]].append(s[1])

    def bucket():
        return {"total": 0, "owned": 0, "complete": 0}

    by_kind = collections.defaultdict(bucket)
    by_set = collections.defaultdict(bucket)
    by_source = collections.defaultdict(bucket)
    missing = {"obtainable": collections.Counter(), "historical": collections.Counter(),
               "unknown": collections.Counter()}
    for r in rows:
        qty = own.get(r["guid"], {}).get("qty", 0)
        has, full = qty > 0, qty >= r["max_copies"]
        buckets = [by_kind[r["kind"]]] + [by_source[c] for c in set(cats[r["guid"]])]
        if r["kind"] == "card" and r["set_kind"] == "main":
            buckets.append(by_set[(r["set_no"], r["set_name"])])
        for b in buckets:
            b["total"] += 1
            b["owned"] += has
            b["complete"] += full
        if not has:
            key = {"yes": "obtainable", "no": "historical"}.get(r["obtainable"], "unknown")
            missing[key][r["kind"]] += 1
    return {
        "account": account.get_account(uid),
        "stardust": account.stardust(uid),
        "by_kind": by_kind,
        "by_set": [{"set_no": k[0], "set_name": k[1], **v} for k, v in sorted(by_set.items())],
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1]["total"])),
        "missing": missing,
        "discrepancies": account.discrepancies(uid),
    }


@app.get("/api/accounts/{account_id}/decks")
def deck_list(account_id: str = Path(description=ACCOUNT_DOC)):
    uid = user_or_404(account_id)
    own = account.ownership(uid)
    db = catalog()
    out = []
    for d in account.decks(uid):
        guids = [c["guid"] for c in d["cards"]] + [g for g in (d["sleeve"], d["gameboard"],
                                                               d["coin"], d["pvp_champion"]) if g]
        info = {r["guid"]: row_out(r) for r in db.execute(
            f"SELECT guid, name, kind, rarity, cost, type, threshold_json, icon, max_copies FROM items "
            f"WHERE guid IN ({','.join('?' * len(guids))})", guids)} if guids else {}
        for c in d["cards"]:
            c.update(info.get(c["guid"], {"name": None}))
            c["owned"] = own.get(c["guid"], {}).get("qty", 0)
        d["cards"].sort(key=lambda c: (c.get("cost") is None, c.get("cost") or 0, c.get("name") or ""))
        for key in ("sleeve", "gameboard", "coin", "pvp_champion"):
            if d[key]:
                d[key] = info.get(d[key], {"guid": d[key], "name": None})
        d["missing_cards"] = sum(max(0, c["qty"] - c["owned"]) for c in d["cards"])
        out.append(d)
    return out


# ------------------------------------------------------------------ admin (optional)

def grant_plan(account_id, items, query, max_items=5000):
    """Resolve a grant request to [(guid, kind, qty, name)].

    items: [{"guid", "qty"}] explicit grants; query: item filters (as for
    /api/items) whose items are filled up to max_copies for the account."""
    uid = user_or_404(account_id)
    kinds = revival.GRANT_KINDS if revival.is_revival(uid) else admin.INVENTORY_KINDS
    plan = []
    if query is not None:
        f = dict(FILTER_DEFAULTS)
        for k, v in query.items():   # same string parameters as /api/items
            if k in ("account", "page", "page_size") or v in ("", None):
                continue
            if k not in f:
                raise HTTPException(400, f"unknown filter: {k}")
            if isinstance(f[k], bool):
                v = v in (True, "true", "1")
            elif k == "pve":
                v = int(v)
            f[k] = v
        f.update(account_id=account_id, owned="incomplete")
        for d in query_items(f):
            plan.append((d["guid"], d["kind"], d["max_copies"] - d["owned"], d["name"]))
    db = catalog()
    for it in items or []:
        r = db.execute("SELECT guid, kind, name, collectible FROM items WHERE guid = ?",
                       (it.get("guid"),)).fetchone()
        if r is None:
            raise HTTPException(404, f"item not found: {it.get('guid')}")
        if r["kind"] == "card" and not r["collectible"]:
            raise HTTPException(400, f"{r['name']} is not a collectible card")
        plan.append((r["guid"], r["kind"], int(it.get("qty") or 1), r["name"]))
    plan = [p for p in plan if p[2] > 0 and (p[1] == "card" or p[1] in kinds)]
    if len(plan) > max_items:
        raise HTTPException(400, f"{len(plan)} items: narrow the filter (limit {max_items})")
    return uid, plan


if admin.ENABLED:
    @app.get("/api/admin/status")
    def admin_status():
        return {"server_running": admin.server_running()}

    @app.post("/api/admin/grant")
    def admin_grant(account_id: str = Body(alias="account", description=ACCOUNT_DOC),
                    items: list[dict] | None = Body(None),
                    query: dict | None = Body(None),
                    dry_run: bool = Body(False)):
        """Grant explicit items and/or fill up everything matching query.
        dry_run returns the plan without writing."""
        uid, plan = grant_plan(account_id, items, query)
        rev = revival.is_revival(uid)
        summary = {"entries": len(plan),
                   "cards": sum(p[2] for p in plan if p[1] == "card"),
                   "items": sum(p[2] for p in plan if p[1] != "card"),
                   "sample": [f"{p[2]}× {p[3]}" for p in plan[:8]],
                   "target": "revival" if rev else "server",
                   "server_running": revival.game_running(uid) if rev else admin.server_running()}
        if dry_run:
            return summary
        entries = [(g, k, q) for g, k, q, _ in plan]
        try:
            result = revival.grant(uid, entries) if rev else admin.grant(uid, entries)
        except (admin.AdminError, revival.GrantError) as e:
            raise HTTPException(409, str(e))
        return {**summary, **result, "server_running": None}


# ------------------------------------------------------------------ art

PLACEHOLDER = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
               '<rect width="64" height="64" fill="#2a2a33"/>'
               '<text x="32" y="38" font-size="20" text-anchor="middle" fill="#666">?</text></svg>')


@app.get("/art/{group}/{name}")
def art(group: str, name: str, size: str = "thumb"):
    name = name.removesuffix(".webp")
    path = thumbs.thumb_path(group, name) if size == "thumb" else thumbs.source_path(group, name)
    if path is None:
        return Response(PLACEHOLDER, media_type="image/svg+xml",
                        headers={"Cache-Control": "max-age=300"})
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "max-age=86400"})


class RevalidatedStatic(StaticFiles):
    """Static files that the browser re-checks (ETag) on every load, so an
    updated app is never mixed with cached ES modules of the old one."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


STATIC = config.ROOT / "static"
if STATIC.is_dir():
    app.mount("/", RevalidatedStatic(directory=STATIC, html=True), name="static")
