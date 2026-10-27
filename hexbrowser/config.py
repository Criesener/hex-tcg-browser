"""Paths used by the browser; override with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEXTCG_ROOT = Path(os.environ.get("HEXTCG_ROOT", ROOT.parent / "HexTCG"))
GAMEDATA = Path(os.environ.get("HEX_GAMEDATA", HEXTCG_ROOT / "data/raw/gamedata"))
SERVER_DB = Path(os.environ.get("HEX_SERVER_DB", HEXTCG_ROOT / "server-state/hconnect.db"))
HEX_SERVER_SRC = Path(os.environ.get("HEX_SERVER_SRC", HEXTCG_ROOT / "ref/hex-server"))
CLIENT_ASSETS = Path(os.environ.get(
    "HEX_CLIENT_ASSETS",
    "/Volumes/Games/SteamLibrary/steamapps/common/HEX SHARDS OF FATE/"
    "Hex.app/Contents/Resources/AssetBundles"))
CLIENT_DATA = Path(os.environ.get("HEX_CLIENT_DATA", CLIENT_ASSETS.parent / "Data"))

CACHE = Path(os.environ.get("HEXBROWSER_CACHE", ROOT / "cache"))
CATALOG = CACHE / "catalog.sqlite"
ART = CACHE / "art"            # art/<group>/<name>.webp, see extract_assets.py
OVERRIDES = ROOT / "sources_overrides.json"
