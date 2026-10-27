"""Reader for the client's gamedata blob.

The file is gzip-compressed text: sections start with ``$$$---$$$<Name>$$--$$``
and hold records separated by ``$$--$$``. Records are near-JSON: trailing
commas, raw control characters and, in a few sections, unquoted keys.
Based on HexTCG/tools/extract_cards.py; splitting on the section marker
itself keeps empty sections (e.g. CardTemplateLayout) from being glued onto
the last record of the previous one.
"""
import gzip
import json
import re

NULL_GUID = "00000000-0000-0000-0000-000000000000"

_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_BARE_KEY = re.compile(r"(?m)^(\s*)(-?[A-Za-z0-9_]+)\s*:")


def parse(rec):
    rec = _TRAILING_COMMA.sub(r"\1", rec)
    try:
        return json.loads(rec, strict=False)
    except json.JSONDecodeError:
        return json.loads(_BARE_KEY.sub(r'\1"\2":', rec), strict=False)


def load(path):
    """Return ``({section: [record dict]}, {section: unparsable count})``."""
    data = gzip.open(path).read().decode("utf-8", "replace")
    out, failed = {}, {}
    for chunk in data.split("$$$---$$$")[1:]:
        name, _, body = chunk.partition("$$--$$")
        name = name.strip()
        recs = out.setdefault(name, [])
        for r in body.split("$$--$$"):
            if r.strip():
                try:
                    recs.append(parse(r))
                except json.JSONDecodeError:
                    failed[name] = failed.get(name, 0) + 1
    return out, failed


def guid(v):
    g = v.get("m_Guid") if isinstance(v, dict) else None
    return None if g in (None, NULL_GUID) else g


def short_type(rec):
    """'Reckoning.Game.InventoryDeckSleeve' -> 'InventoryDeckSleeve'."""
    return rec.get("_t", "").rsplit(".", 1)[-1]


def art_name(path):
    """'_ArtSource\\a0007500-a0007999\\a0007547_SLS.PNG' -> 'a0007547_SLS'."""
    if not path:
        return ""
    return re.split(r"[\\/]", path)[-1].rsplit(".", 1)[0]
