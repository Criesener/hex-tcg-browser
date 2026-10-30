# Konzept: Lokaler HexTcgBrowser

## Context
Der private HEX-Server (`~/Projekte/HexTCG`, Python-Reimplementierung `ref/hex-server`, Docker, SQLite `server-state/hconnect.db`) läuft. Es fehlt ein Ersatz für die alte Seite hextcgbrowser: eine Übersicht über alle Karten, Mercenaries, Sleeves, Equipment und sonstigen Items, mit drei Fragen pro Item: **Was gibt es? Was besitze ich? Wie bekomme ich es?** Vorbild für Bedienung und Filter ist vs.tcgbrowser.com (AngularJS-SPA mit `#!/cards`, `#!/decks`, vielen Dropdown-Filtern, Sortierung nach Cost/Name/Set-Nr. und einer Karten-Detailansicht mit Vor/Zurück).

Der Server bietet **keine Collection-API**. `proxy.py` beantwortet `/collection` mit 404. Der Browser liest deshalb die SQLite-DB direkt (read-only) und die statischen Daten aus `data/raw/gamedata` und `data/cards.json`.

Entscheidungen: **Python-Backend + Vanilla-JS-SPA ohne Build-Schritt**, **UI nur auf Englisch**, **standardmäßig nur lesen**, optional ein Admin-Modus zum Gutschreiben von Items.

---

## 1. Datenquellen (vorhanden)

| Was | Quelle | Bemerkung |
|---|---|---|
| Karten (7213) | `HexTCG/data/cards.json` | `id` = `card_templates.guid` = `collections.card_template_id`; `set`, `rarity`, `faction`, `threshold`, `art`, `pve`, `tradeable` |
| Items (2699) | `data/raw/gamedata`, Sektion `InventoryItemData` | Equipment 1935, DeckSleeve 425, Mercenary 86, Gem 73, CardPack 41, StarterPack 38, TreasureChest 36, Gameboard 15, Coin 8 |
| Herkunftstexte | `m_Reason` (Sleeves, Gameboards, Coins), `m_Description` (Mercs, Packs), `m_DesignNotes` (Equipment) | z. B. „Awarded to Knight Tier Kickstarter backers.“, „Set 3 WOF“, „FRA“, „az2 krakens gold“ |
| Mercenary-Stats | `MercenaryTemplate` (166) | Text, HP, Passive, Upgrade |
| Sets | `CardSetTemplate` (58) | Name, Nr., Release-Datum |
| Starter-Deck-Inhalte | `InventoryStarterPack.m_DeckTemplateId` → `DeckTemplate` | Karte X ist in Starter Y |
| Equipment → Karten-Upgrade | `hconnect.db.equipment_card_variants` (2732) | „verbessert Karte X“ |
| Store, Packs, Chests | `hconnect.db`: `store_items`, `pack_set_map`, `chest_templates`, `conversation_rewards`, `fra_challenges`, `quest_templates`, `tournament_types` | Herkunft: Store-Preis, Booster-Set, Kampagnenbelohnung |
| Account | `hconnect.db`: `users`, `collections`, `card_instances` (`is_extended_art`), `player_inventory`, `stardust`, `champions`, `decks`, `treasure_chests` | Alle Nicht-Karten-Items liegen in `player_inventory` (nach `template_guid`) |
| Kartenbilder | `data/art/aNNNNNNN.png` (512², 1,8 GB) | 6888 von 6896 Art-Referenzen vorhanden |

| Item-Icons (alle Nicht-Karten) | Client `…/Hex.app/Contents/Resources/AssetBundles/general/icons.ab` (2390 Texturen, meist 128²) | Name = `m_ArtNumber` des Items. Abgedeckt: Equipment 1935/1935, Mercenaries 83/83, Sleeves 408/410, Battleboards 15/15, Packs 41/41, Starter 28/28, Chests 33/33, Coins 7/7. Gems haben kein `m_ArtNumber`. |
| Sleeve-Vollbilder | `AssetBundles/general/DeckSleeves.harc` (1117 Texturen, `aNNNNNNN_SL`/`_SLS`, 512²) | Großansicht in der Detailseite |
| Merc-/Champion-Portraits | `AssetBundles/cardsets/championsandmercenaries.harc` (608, 1024²), `set0X_pve_mercenaries.harc` | Großansicht |
| Battleboard-Vorschau | in `icons.ab` (512×256 / 1024×512) | |

**Korrektur gegenüber der ersten Analyse:** Die Bilder sind im Client vorhanden. Das bisherige `tools/extract_art.py` hat sie aus zwei Gründen verpasst:
1. Es durchsucht nur `cardsets/`. `general/icons.ab` und `DeckSleeves.harc` wurden nie verarbeitet.
2. Es überspringt Texturen, deren Dateiname schon existiert. Deshalb kamen aus den Equipment- und Merc-Bundles fast keine neuen Dateien heraus.

**Besonderheit Equipment-Icons:** Sie sind DXT5 mit einem Alpha-Kanal, der nahezu 0 ist. Nur RGB verwenden (Icon auf schwarzem Grund). Alpha nicht übernehmen, sonst ist das Bild unsichtbar bzw. weiß.

Weiterhin fehlen echte Drop-Wahrscheinlichkeiten und Kickstarter-Tier-Tabellen. Gem-Icons kommen evtl. aus `cardsets/herofallgems.harc` (offen).

Wiederverwendbar:
- `HexTCG/tools/extract_cards.py`: `sections()`, `parse()`, `guid()`. Der Parser braucht zwei Fixes: unquotierte Keys per Regex `(?m)^(\s*)(-?[A-Za-z0-9_]+)\s*:` quoten und `json.loads(strict=False)` verwenden. Außerdem muss der angeklebte `CardTemplateLayout`-Marker entfernt werden, sonst fehlt eine Karte.
- `ref/hex-server/profile_db.py`: `db_add_inventory`, `db_grant_collection_cards`, `db_get_decks`. Wird nur im Admin-Modus genutzt.
- `ref/hex-server/hex_mcp.py`: Lookups für Records (Referenz).

---

## 2. Architektur

```
HexTcgBrowser/
  hexbrowser/
    config.py          # Pfade (HEXTCG_ROOT, DB, gamedata, art) per ENV/CLI
    gamedata.py        # robuster Parser für das gamedata-Blob (übernommen + gefixt aus extract_cards.py)
    build_catalog.py   # CLI: gamedata + cards.json + statische DB-Tabellen → catalog.sqlite
    sources.py         # Regelwerk: Rohtexte/Sets → normierte "Obtain Sources"
    account.py         # read-only Zugriff auf hconnect.db (Accounts, Besitz, Decks)
    admin.py           # optional: Items gutschreiben (nur bei gestopptem Server, mit Backup)
    thumbs.py          # PNG → WebP-Thumbnails (256px) in cache/, on demand
    extract_assets.py   # Client-Bundles → cache/icons/<kind>/<art>.webp (icons.ab, DeckSleeves.harc,
                       #   championsandmercenaries.harc); Equipment nur RGB; Ziel pro Item-Art
                       #   getrennt, damit es keine Namenskollisionen mit Kartenart gibt
    server.py          # FastAPI-App: JSON-API + statische Dateien + Bilder
  static/
    index.html  app.js  router.js  views/*.js  styles.css
  cache/               # catalog.sqlite, thumbs/ (gitignored)
  run.sh               # build (falls nötig) + uvicorn auf 127.0.0.1:8090
```

- **Katalog und Account sind getrennt.** `catalog.sqlite` wird einmal aus statischen Daten gebaut (idempotent, `--rebuild`). Account-Daten werden pro Request live und read-only aus `hconnect.db` gelesen (`file:...?mode=ro`, WAL-sicher). So sind neue Packs sofort sichtbar.
- Abhängigkeiten in der vorhandenen `.venv`: `fastapi`, `uvicorn` und `Pillow`. Sonst nur die Standardbibliothek.
- Port 8090, damit es keinen Konflikt mit dem Server (8081/9933) gibt.

### Katalog-Schema (catalog.sqlite)
- `items(guid PK, kind, name, set_name, set_no, rarity, subtype, faction, cost, threshold_json, attack, defense, text, flavor, artist, art, pve, tradeable, is_promo, is_alternate, base_guid, extra_json)`
  - `kind` ∈ card, equipment, mercenary, sleeve, gameboard, coin, gem, pack, starter, chest, champion
  - Alternate-Arts zeigen über `base_guid` auf die Basiskarte (gleicher Name).
- `sources(item_guid, category, detail, raw_text)`: mehrere Einträge pro Item möglich.
- `sets(guid, no, name, release_date, kind)` (Main / PvE / Promo / Alternates / AI)
- `relations(from_guid, rel, to_guid)`: `upgrades_card` (Equipment → Karte), `in_starter` (Karte → Starter), `merc_upgrade`, `pack_of_set`.

### Herkunfts-Klassifikation (`sources.py`)
Das Regelwerk ist geordnet. Jede Regel prüft Item-Art, Set und Rohtext und vergibt eine Kategorie:

| Kategorie | Erkennung |
|---|---|
| Booster (Set N) | Karte aus Haupt-Set, nicht PvE |
| Primal / Special Pack | `pack_set_map.is_primal`, `m_CardPackType` |
| Starter Deck | `relations.in_starter` |
| Kickstarter (+ Tier) | `m_Reason` „… Tier Kickstarter backers“ → Tier extrahieren; „Kickstarter“ in Description/DesignNotes; Set `Set01_Kickstarter*` |
| Treasure Chest (Set N) | „Chest Loot“, „<Set> Chest“, `is_chest_loot` |
| Wheel of Fate | „WOF“, „Wheels of Fate“ |
| PvE Campaign / AZ1 / AZ2 / Dungeon | Sets `AZ1/AZ2`, „AZ1 PVE PACK“, „az2 …“, `conversation_rewards` |
| Frost Ring Arena / Arena | „FRA“, „Arena“, `fra_*` |
| Ladder / Tournament | „Ladder“, „Season“, `tournament_types` |
| Convention / Promo / Holiday | „GenCon“, „PAX“, Holiday, `_PvE_Promo`, `chest_templates.promotional_id` |
| Store | `store_items` (Preis + Währung) |
| Talent / Created / AI only | Sets `*_Talents`, `*_Created_Effects`, `AI Only Cards` → nicht sammelbar |
| Unknown | Fallback, Rohtext wird angezeigt |

Zusätzlich gibt es die Spalte **obtainable_on_private_server**: Ist das Item auf diesem Server erhältlich (Store, Pack, Chest, implementierte PvE) oder historisch (Kickstarter, Ladder, Convention)? Das ist der Kern der alten hextcgbrowser-Funktion. Eine Datei `sources_overrides.json` erlaubt manuelle Korrekturen.

### Account-Logik (`account.py`)
- `list_accounts()`: Namen, Gold, Platin, Level, Champions.
- `ownership(user_id)`: `{guid: {qty, extended_art_qty}}` aus `collections` und `card_instances` plus `player_inventory`.
- `decks(user_id)`: beide Speicherformate auflösen (Karten-GUIDs oder `instance_id` → `card_instances.template_guid`).
- Abgeleitet werden: owned, missing, incomplete playset (< 4, bei Unique < 1) und Completion pro Set, Item-Art und Herkunft.

---

## 3. API (FastAPI, JSON)

| Endpoint | Zweck |
|---|---|
| `GET /api/meta` | Filterwerte (Sets, Rarities, Types, Factions, Sources, Kinds) |
| `GET /api/items?kind=&q=&text=1&set=&rarity=&type=&faction=&cost=&shard=&atk=&def=&source=&pve=&owned=owned\|missing\|incomplete&account=&sort=&page=` | Liste mit Filtern und Paging |
| `GET /api/items/{guid}` | Detail inkl. Quellen, Relationen, Alternates, Besitz |
| `GET /api/accounts` / `GET /api/accounts/{id}/summary` | Accounts und Completion-Statistiken |
| `GET /api/accounts/{id}/decks` | Decks mit aufgelösten Karten, fehlende Karten markiert |
| `GET /art/{art}?size=thumb\|full` | Bild (Thumbnail-Cache) bzw. Platzhalter |
| `POST /api/admin/grant` | nur mit `--admin`, siehe Abschnitt 5 |

Filtern und Sortieren laufen serverseitig per SQL auf catalog.sqlite. Der Besitz-Filter joint gegen ein Ownership-Dict, das pro Request gelesen wird (klein, schnell).

---

## 4. Frontend (Vanilla-JS-SPA, UI Englisch)

Hash-Router im Stil des Vorbilds:
- `#!/cards`: Grid- oder Listenansicht mit Thumbnails und Besitz-Badge (z. B. „3/4“, grün/gelb/grau). Filterleiste: Name/Text-Suche, Set, Type, Rarity, Faction, Cost (0–7+), Threshold-Shards (Blood/Diamond/Ruby/Sapphire/Wild), ATK/DEF, PvE/PvP, Source, Owned/Missing/Incomplete, „hide alternates/AI-only“. Sortierung nach Cost, Name, Set No. und Rarity.
- `#!/equipment`, `#!/mercenaries`, `#!/sleeves`, `#!/other` (Gameboards, Coins, Gems, Packs, Chests, Starter): gleiche Listenkomponente mit art-spezifischen Spalten. Bei Equipment sind das Slot, Modifier und verbesserte Karte.
- `#!/item/{guid}`: Detail als Modal mit Prev/Next. Inhalt: großes Bild, Text, Herkunft (Kategorie, Detail, Rohtext, „available on this server: yes/no“), Alternates, Starter-Zugehörigkeit, Equipment-Varianten, Besitz.
- `#!/collection`: Account-Auswahl (oben rechts, wird in `localStorage` gemerkt). Dashboard mit Completion pro Set, Kind und Source (Balken) sowie Listen „missing but obtainable here“ und „missing, historical only (Kickstarter etc.)“.
- `#!/decks`: Decks des Accounts mit fehlenden Karten. Der Deckbuilder ist bewusst nicht im MVP.
- Filterzustand steht in der URL (teilbar, Back-Button funktioniert). Lazy-Loading der Bilder (`loading="lazy"`).

---

## 5. Optionaler Admin-Modus („Grant“)
- Nur aktiv mit `run.sh --admin`. Sonst gibt es keinen Schreib-Endpoint.
- Vor jedem Schreibvorgang wird geprüft, dass der Server gestoppt ist (Port 9933 nicht erreichbar bzw. `docker inspect hex-server` meldet nicht running). Läuft er, wird mit Hinweis abgelehnt, weil der Server sonst den Stand überschreibt.
- Vorher kommt ein automatisches Backup `hconnect.db` → `server-state/hconnect.db.browser-<timestamp>.bak`.
- Geschrieben wird über die Funktionen des hex-servers (`profile_db.py`: `db_next_card_instance_id`, `db_grant_collection_cards`, `db_insert_collection_card_instances`, `db_grant_inventory_item`), genau wie `new_player.py` die Startsammlung vergibt. So bleiben `collections` und `card_instances` konsistent. Alles läuft in einer Transaktion und wird in `cache/admin.log` protokolliert.
- Umgesetzt in `hexbrowser/admin.py`. `profile_db` wird mit einem leeren Platzhalter für das Modul `db` geladen, weil der Import des echten `db` beim Laden eine Datenbank öffnet und befüllt.
- API (nur mit `--admin`): `GET /api/admin/status`, `POST /api/admin/grant {account, items:[{guid,qty}] | query:{Filter wie /api/items}, dry_run}`. Mit `query` wird jedes Item der gefilterten Liste auf ein volles Playset aufgefüllt.
- UI: Die Detailansicht hat ein Mengenfeld mit „Grant…“, die Listenansicht einen Button „Grant missing…“ für die aktuelle Filterliste (z. B. Set + Rarity). Vorher läuft immer ein Probelauf, der in einem eingeblendeten Bereich auf der Seite angezeigt wird. Läuft der Server, ist „Grant“ gesperrt.

### Export und Gems (Phase 4)
- `GET /api/items.csv` nimmt dieselben Filter wie `/api/items` und liefert Name, Kind, Set, Rarity, Obtainable, Quellen, Owned, Max und Missing. Die Listenansicht hat „Export CSV“. Die Collection-Seite hat CSV-Links pro Missing-Kategorie und pro Set sowie eine komplette Missing-Liste.
- Gem-Icons: Die 73 Gems haben kein `m_ArtNumber`. Das Bild kommt aus den Kugel-Texturen in `cardsets/herofallgems.harc`, zugeordnet über die Threshold-Farbe; Major bekommt den Bronzering, Minor den dunklen Ring, Gems ohne Farbe die farblose Kugel. Der Server vergibt Gems nicht als Item, daher steht die Herkunft auf Unknown.

---

## 6. Umsetzungsphasen
1. **Daten-Fundament:** `gamedata.py` (gefixter Parser), `build_catalog.py`, `sources.py` mit Regeltabelle, `extract_assets.py` (Item-Icons und Großbilder aus dem Client). Bericht: Anzahl pro Kind und Source, Anteil „Unknown“, Icon-Abdeckung pro Kind.
2. **Backend:** `account.py`, `server.py` mit Items-, Meta-, Account- und Art-Endpoints, `thumbs.py`.
3. **Frontend-MVP:** Cards-View, Detail-Modal, Account-Auswahl, Owned-Filter, danach Equipment-, Mercenary- und Sleeve-Views, Collection-Dashboard, Decks.
4. **Erweiterungen:** Admin-Grant; Gem-Icons; Export (CSV „missing list“).

---

## 7. Verifikation
- `python -m hexbrowser.build_catalog` → catalog.sqlite enthält 7214 Karten (inkl. der bisher verlorenen), 1935 Equipment, 425 Sleeves und 86 Mercs. Stichproben: Sleeve mit „Knight Tier Kickstarter“ wird als Kickstarter/Knight klassifiziert, Equipment „FRA“ als Frost Ring Arena.
- Account-Check gegen die DB: Der eigene Account zeigt 65 verschiedene Karten und 655 Instanzen, 11 Shards-of-Fate-Booster, den „Windbourne Acolyte Sleeve“ und den Merc „The Transcended“ als owned.
- Auf beiden Decks (GUID- und Instance-Format) werden alle Karten aufgelöst.
- Live-Test: Server starten, im Client ein Pack öffnen, Browser neu laden. Die neuen Karten erscheinen ohne Rebuild.
- Read-only-Garantie: Ohne `--admin` liefert ein Schreibversuch 404. Die DB-Datei bleibt unverändert (mtime/Checksumme vorher und nachher).
- Admin: Bei laufendem Server wird der Grant abgelehnt. Bei gestopptem Server wird ein Backup angelegt, das Item vergeben, und nach `hex-server.sh start` ist es im Client sichtbar.
- UI im Browser (Claude in Chrome): Filter-Kombinationen, Prev/Next im Modal, URL-Zustand, Lazy-Loading bei 7000 Karten.

---

## 8. Kartenrahmen im Original-Look
- Der Rahmen besteht aus den Original-Sprites des Clients. `resources.assets` enthält drei NGUI-`UIAtlas`-Objekte, `A_CardTemplate_Frames`, `_Elements` und `_Icons`, mit 100 benannten Sprites:
  - `<Farbe>_1..4` (Rahmenleisten) und `<Farbe>_Text` (Textfeld), jeweils für Blood, Diamond, Ruby, Sapphire, Wild, Multi, Artifact, Shardless und Class
  - `TitleBar`, `TypeBar`, `ThresholdBar`, `ManaCost[Immortal]`, `AtkDefFrame`, `Attack-/DefenseIcon`, `BottomBar`, `FactionRarity`
  - `Threshold_*`, `Rarity_*`, `Faction_*`, `SetIcon01–09`, `Immortal`, `PVE`
- Der Build hat keine Typinformationen. `extract_assets.ngui_sprites()` liest deshalb die Rohdaten: Zähler, dann pro Sprite der Name und 13 int32 (x, y, w, h, Border, Padding, rotated).
- Das Padding ist der beschnittene Rand der vollen Karte. Daraus ergibt sich die Position jedes Teils auf der Karte. `extract_assets frame` schreibt `cache/art/frame/*.webp` und `layout.json`, die per `/api/meta` (`frame`) ausgeliefert werden.
- `static/js/card.js` schichtet die Sprites an diesen Positionen; Text, Kosten und ATK/DEF liegen darüber.
  - Rahmenfarbe: eine Threshold-Farbe ergibt deren Rahmen, mehrere ergeben `Multi`; ohne Farbe gilt bei Artefakten `Artifact`, sonst `Shardless`.
  - Das Kosten-Hexagon ist immer `ManaCost`, das dunkle wie im Original „Maggot Swarm“. PvE-Karten bekommen zusätzlich das `PVE`-Symbol. `ManaCostImmortal` und der Stern `Immortal` werden nicht verwendet.
  - Alle Karten bekommen rechts die Runenleiste `GemBar`, wie im Original. PvE-Karten bekommen statt `TitleBar` die Titelleiste mit Goldranke `TitleBarPVE_1` und dazu die Ranke `TitleBarPVE_2`.
  - Gem-Sockel: Die Anzahl kommt aus `m_SocketCount`; ob Major oder Minor, wird aus „Socketable Major/Minor“ im Kartentext gelesen (Major oben, Rest Minor). Sie liegen mittig auf der Runenleiste: einzeln bei 37,9 % der Höhe, zwei im Abstand von 6,3 % um 37,5 %, gemessen an Client-Screenshots. Grafiken: `GemSocket_Major` (Bronze) und `GemSocket_Minor` (Silber).
  - ATK/DEF-Zahlen sitzen auf dem deckenden Kreis von `AtkDefFrame` (x 0–82, y 7–88 von 88 px, der Rest ist Schatten). Der rechte Kreis wird gespiegelt.

---

## 9. HEX-Revival-Spielstände als zweite Account-Quelle
- `hexbrowser/revival.py` liest die Spielstände des Mods HEX Revival nur lesend.
  - **Pfade:** Offline-Accounts liegen in `HEX_REVIVAL_SAVES`, mehrere Installationen getrennt durch `:` (Standard: Steam-Installation `…/steamapps/common/HEX SHARDS OF FATE/…`, `/Volumes/Games/HEX-Revival/…` und `/Volumes/Games/HEX-Test-Mac/…`). Der Online-Account liegt jeweils in `HexRevivalOnline` daneben.
  - **IDs:** `rev:<Installation>:<Ordner>` bzw. `rev:<Installation>:online`. `resolve()` akzeptiert auch den bloßen Ordnernamen, wenn er eindeutig ist.
- **Formate:**
  - `account.txt`: `key=value`; `unlock=1` heißt, alles ist freigeschaltet. `lastplayed` steht in .NET-Ticks.
  - `collection.txt`: `<guid> <anzahl>`.
  - `inventory.txt`: `<guid> <anzahl>` für Equipment, Sleeves, Packs und Stardust. Stardust wird zusätzlich als Stardust des Accounts angezeigt.
  - `chests.txt`: `<id> <?> <?> <?> <set-guid>`, nicht ausgewertet.
  - `decks.txt`: Blöcke aus `DECK|id|name|?|champion|sleeve|board|coin|…`, `CARDS|guid,…` mit einer GUID pro Kopie, sowie `SIDE|`, `EQUIP|` und `TALENT|`.
  - `champions.txt`: `id|name|level|…`.
- `account.py` delegiert jede Funktion bei `rev:`-IDs an `revival.py`. `list_accounts()` liefert beide Quellen mit dem Feld `source`, die API bleibt unverändert.
- **Bei `unlock=1`:** Besessen sind alle sammelbaren Karten (`max_copies`) und alle Equipment-Items. Das entspricht der README des Mods („every card (4 copies) … and every equipment“).
- **Grenzen:**
  - Die Spielstände enthalten keine Mercenaries.
  - `online_profile.json` wird nie gelesen.
- **Admin-Grant für Revival-Accounts** (`revival.grant`):
  - **Ziel:** Karten gehen nach `collection.txt`. Equipment, Sleeves, Mercenaries und Packs gehen nach `inventory.txt` (`GRANT_KINDS`, die Arten, die der Mod dort speichert). Bestehende Zeilen werden hochgezählt, neue GUIDs angehängt, geschrieben wird atomar über eine `.tmp`-Datei.
  - **Gesperrt, solange `Hex.app` aus derselben Installation läuft:** geprüft per `ps`. Das Spiel hält den Account im Speicher und überschreibt die Dateien beim nächsten Speichern.
  - **Backup:** vorher nach `cache/revival-backups/<Installation>/<Account>/<Zeit>/`. Protokoll in `cache/admin.log`.
  - **Accounts mit `unlock=1`:** abgelehnt, sie haben ohnehin alles.
