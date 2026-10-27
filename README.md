# HEX TCG Browser

A local collection browser for **HEX: Shards of Fate**, made as the companion
to the private server [Criesener/hex-server](https://github.com/Criesener/hex-server).
It brings back what the old *hextcgbrowser* site did: load your account and see
for every card, mercenary, sleeve, piece of equipment and other item:

- **what exists:** the full catalog from the client's gamedata
- **what you own:** read live from the server's `hconnect.db`
- **how to get it:** booster set, starter deck, store, campaign or PvE reward,
  Frost Ring Arena, Kickstarter tier, and whether it is obtainable on this
  server at all

Operation and filters follow [vs.tcgbrowser.com](https://vs.tcgbrowser.com/#!/cards).
Cards are drawn with the client's original card-frame sprites: threshold gems,
gem sockets, PvE ornaments and ATK/DEF circles.

> Apart from the screenshots below, no game assets are part of this repository.
> Images and data are extracted locally from your own installation of the HEX
> client.

![Card grid with filters](docs/screenshots/cards.png)

## Features

- **Views:** Cards, Equipment, Mercenaries, Sleeves and Other (gameboards,
  coins, gems, packs, chests, starters), each as a grid or a list.
- **Filters:** search, set, type, rarity, faction, cost, threshold shards,
  ATK/DEF, PvE/PvP, obtain source, and owned / missing / incomplete. The
  filter state is kept in the URL.
- **Detail view:** the card in its in-game look, plus sources with the raw
  game text, alternate arts, starter decks, equipment variants and copies
  owned. Prev/next moves through the list.
- **Collection:** completion per set, kind and source. Missing items are split
  into "obtainable here" and "historical only".
- **Decks:** the account's decks with the cards each one is missing.
- **CSV export:** of any filtered list, or of what is missing.
- **Admin mode** (optional, off by default): grant cards and items to an
  account, see below.

## Screenshots

**Card detail:** the in-game frame with a gem socket, obtain sources,
equipment, other versions, and a grant dry run in admin mode. Granting is
blocked here because the hex-server is running.

![Card detail with admin grant](docs/screenshots/card-detail-admin.png)

| | |
|---|---|
| **Equipment** ![Equipment grid](docs/screenshots/equipment.png) | **Equipment detail**, with the cards it upgrades ![Equipment detail](docs/screenshots/equipment-detail.png) |
| **Mercenaries** ![Mercenary grid](docs/screenshots/mercenaries.png) | **Mercenary detail**, a historical convention reward ![Mercenary detail](docs/screenshots/mercenary-detail.png) |
| **Sleeves** ![Sleeve grid](docs/screenshots/sleeves.png) | **Battleboards** ![Battleboards](docs/screenshots/battleboards.png) |

## How it fits together

```
HEX client install ──► extract_assets ──► cache/art/…     (images, frame sprites)
client Data/gamedata ─► build_catalog ──► cache/catalog.sqlite
hex-server hconnect.db ─────────────────► read-only, live (ownership, decks)
                                             │
                          FastAPI (hexbrowser/server.py) + Vanilla-JS SPA (static/)
                                             │
                                  http://127.0.0.1:8090
```

The browser never needs the server to be running. It opens `hconnect.db` with
`mode=ro` and picks up new cards (an opened pack, say) on the next page load.
The server has no collection API.

## Requirements

- Python 3.11+ (developed on 3.13)
- A local install of the HEX client. Images and the card frame are extracted
  from it.
- The client's `Data/gamedata` file, which is also the data source of hex-server
- A [hex-server](https://github.com/Criesener/hex-server) setup with its
  SQLite database `hconnect.db`
- Admin mode only: before writing it checks that the server is stopped. It asks
  Docker about the `hex-server` container and falls back to probing port 9933.

## Setup

The default layout keeps everything next to each other in one parent
directory:

```
Projekte/
  HexTcgBrowser/            this repository
  HexTCG/
    data/raw/gamedata       copy of the client's Data/gamedata
    server-state/hconnect.db
    ref/hex-server/         checkout of Criesener/hex-server (admin mode only)
    server/hex-server.sh    start/stop helper for the Docker container
```

```sh
git clone https://github.com/Criesener/hex-tcg-browser.git HexTcgBrowser
cd HexTcgBrowser
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

The first start extracts the images from the client (several minutes, about
400 MB in `cache/art`) and builds the catalog. Then open
<http://127.0.0.1:8090>.

### Paths

All paths can be overridden with environment variables (`hexbrowser/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `HEXTCG_ROOT` | `../HexTCG` | base directory for the defaults below |
| `HEX_GAMEDATA` | `$HEXTCG_ROOT/data/raw/gamedata` | the client's gamedata blob |
| `HEX_SERVER_DB` | `$HEXTCG_ROOT/server-state/hconnect.db` | server database (read-only) |
| `HEX_SERVER_SRC` | `$HEXTCG_ROOT/ref/hex-server` | hex-server source, used by admin mode |
| `HEX_CLIENT_ASSETS` | Steam path on `/Volumes/Games/…/Hex.app/Contents/Resources/AssetBundles` | client asset bundles |
| `HEX_CLIENT_DATA` | `$HEX_CLIENT_ASSETS/../Data` | client `resources.assets` (card frame) |
| `HEX_SERVER_CONTAINER` | `hex-server` | Docker container checked by admin mode |
| `HEXBROWSER_CACHE` | `./cache` | extracted images, thumbnails, catalog |
| `HEXBROWSER_PORT` | `8090` | HTTP port |

## Usage

```sh
./run.sh              # serve (extract assets / build the catalog if missing)
./run.sh --rebuild    # rebuild the catalog first (after a gamedata update)
./run.sh --admin      # additionally enable granting items
```

Individual steps:

```sh
.venv/bin/python -m hexbrowser.extract_assets [--force] [group ...]   # cards portraits icons sleeves ui frame
.venv/bin/python -m hexbrowser.build_catalog
```

Choose your account at the top right: by login name or account id. The choice
is remembered in the browser.

## Admin mode

`./run.sh --admin` adds "Grant…" to the detail view and "Grant missing…" to
filtered lists, for example every missing card of a set up to a full playset.
The safeguards:

- Write endpoints exist only in this mode. Without it the API is read-only.
- Every grant is a dry run first and is confirmed in the page.
- Writing is refused while the hex-server is running, because the server would
  overwrite the change. Stop it first with `HexTCG/server/hex-server.sh stop`.
- `hconnect.db` is backed up first, to `hconnect.db.browser-<timestamp>.bak`.
- The grant goes through hex-server's own `profile_db` functions, the same ones
  `new_player.py` uses, in a single transaction. That keeps `collections` and
  `card_instances` consistent. Each grant is logged to `cache/admin.log`.

## API

| Endpoint | |
|---|---|
| `GET /api/meta` | sets, filter values, frame layout, admin flag |
| `GET /api/items` | filtered, sorted, paginated list (`account=` adds ownership) |
| `GET /api/items.csv` | the same filters as CSV |
| `GET /api/items/{guid}` | item detail with sources, alternates, variants |
| `GET /api/accounts` | accounts in `hconnect.db` |
| `GET /api/accounts/{id}/summary` | completion per set / kind / source |
| `GET /api/accounts/{id}/decks` | decks with the cards each is missing |
| `GET /art/{group}/{name}?size=thumb\|full` | extracted images (WebP) |
| `GET /api/admin/status`, `POST /api/admin/grant` | admin mode only |

## Project layout

```
hexbrowser/
  config.py          paths (environment variables)
  gamedata.py        parser for the client's gamedata blob
  build_catalog.py   gamedata + server tables → cache/catalog.sqlite
  sources.py         raw texts and sets → normalized obtain sources
  account.py         read-only access to hconnect.db
  admin.py           optional grants through hex-server's profile_db
  extract_assets.py  client bundles → cache/art/<group>/*.webp, card-frame atlas
  thumbs.py          on-demand thumbnails
  server.py          FastAPI app
static/              Vanilla-JS SPA (no build step)
run.sh               start script
KONZEPT.md           design notes (German)
```

## Related

- [Criesener/hex-server](https://github.com/Criesener/hex-server): the private
  server this browser reads from, a fork of
  [MTGQuarters/hex-server](https://github.com/MTGQuarters/hex-server)

HEX: Shards of Fate is a trademark of its respective owners. This is an
unofficial fan project for private use with a private server.
