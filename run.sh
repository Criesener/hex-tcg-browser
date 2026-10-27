#!/bin/zsh
# Start the local HexTcgBrowser on http://127.0.0.1:8090
#   ./run.sh            build the catalog if missing, then serve
#   ./run.sh --rebuild  rebuild the catalog first
#   ./run.sh --admin    also enable granting items to accounts (writes
#                       hconnect.db; only while the hex-server is stopped)
set -e
cd "$(dirname $0)"
PY=.venv/bin/python
REBUILD=0
for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD=1 ;;
    --admin) export HEXBROWSER_ADMIN=1 ;;
    *) echo "usage: $0 [--rebuild] [--admin]"; exit 1 ;;
  esac
done
[[ -f cache/art/icons/manifest.json ]] || $PY -m hexbrowser.extract_assets
[[ -f cache/art/frame/layout.json ]] || $PY -m hexbrowser.extract_assets frame
if [[ $REBUILD == 1 || ! -f cache/catalog.sqlite ]]; then
  $PY -m hexbrowser.build_catalog
fi
exec .venv/bin/uvicorn hexbrowser.server:app --host 127.0.0.1 --port ${HEXBROWSER_PORT:-8090}
