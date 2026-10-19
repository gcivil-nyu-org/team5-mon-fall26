# Progress and handoff

Newest entry at the top. Every working session ends by adding an entry.

Entry format:
- Date and story (for example, US1 #3)
- What changed (files, endpoints, tables)
- Decisions made (also add them to `decisions.md`)
- Tests: what passes, what is missing
- Next step, and anything that is blocked

## Current sprint
- Sprint goal: TBD (set by the Product Owner)
- Milestone: TBD

## Log

### 2026-10-19 — US4 #6 (time filters)
**What changed:**
- Added weekday and hour filters to the map; changes refresh the map statistics and selected-zone summary.
- Extended `GET /api/zones` with each zone's fare range and average duration.
- Updated the HLD and `decisions.md`.

**Decisions made (also in `decisions.md`):** filters default to the current NYC weekday and hour; selecting a zone shows its summary.

**Tests:** `manage.py check` and the JavaScript syntax check passed. Django tests could not run because PostgreSQL is not listening on `localhost:5432`.

**Next step:** start PostgreSQL and run the Django tests.

### 2026-10-18 — US0a #20 (import_trips built)
**What changed:**
- `python manage.py import_trips --month YYYY-MM [--month ...] [--data-dir PATH]` in `zones/management/commands/import_trips.py`.
- `zones/importer/` package: `read.py` (Parquet and zone lookup, raw column names), `clean.py` (7 cleaning rules), `aggregate.py` (per-month partial totals merged across months, integer cents), `load.py` (zone upsert + stats DELETE/bulk insert in one transaction, then ANALYZE), `download.py` (urllib, `.part` then rename), `report.py`, `pipeline.py`.
- `zones/data/taxi_zone_lookup.csv` (TLC lookup, 265 zones).
- `requirements.txt`: pandas 3.0.6, pyarrow 26.0.0, numpy 2.5.4.
- README: "Import the trip data". HLD sections 4 and 9.4: one or more months (wiki still to update).
- Real run, March to May 2026 on local Postgres: 11,874,527 read, 11,244,605 kept (5.30% removed; 5.67% / 4.99% / 5.25% per month), 37,949 zone cells, 1,306,474 route cells, 265 zones. About 90 to 100 s and about 1.2 GB peak memory. A second run gave identical counts, trip sums, and fare/duration checksums.

**Decisions made (also in `decisions.md`, 2026-10-18 section):**
- Removed trips counted once, under the first rule they fail (fixed order). Zone IDs not in the lookup count as unknown. Missing values fail the rule that checks them.
- Money in integer cents; `fare_avg` rounded half up once when written. DELETE, not TRUNCATE. A repeated `--month` is an error. numpy pinned.

**Tests:** `manage.py test`: 79 tests, OK. One test per cleaning rule with boundary cases, aggregation exactness across months, load/replace/rollback, download without network, report, and the command end to end on tiny Parquet files.

**Next step:**
- Open the PR for `us0a-trip-import` into `develop`; update the HLD wiki page to match sections 4 and 9.4.
- No `payment_type` 6 trips exist in March to May 2026, so the voided rule removed 0 there (it is tested).
- Separate small PR (team decision): the explicit index on each stats table duplicates its unique constraint's index.
- Moving US0a to Done still needs the Integration deploy (waits on AWS). Peak memory (about 1.2 GB) means the import needs a machine with 2 GB or more.

### 2026-10-17 — US0a #20 (planning, no code yet)
**What changed:**
- Split US0 (#16) into US0a #20 (trip import and stats) and US0b #21 (zone shapes), as GitHub sub-issues.
- Added `docs/stories/US0a.md` and `docs/stories/US0b.md`; updated `docs/stories/README.md` and the stack and stories lines in `CLAUDE.md`.
- Analysed the January to August 2026 yellow taxi files with a one-off script (not committed) to choose the months, cleaning rules, and fare column.

**Decisions made (also in `decisions.md`):**
- Load March to May 2026; the import command takes one or more months.
- Fare statistics use fare before tip (`total_amount - tip_amount`).
- Cleaning rules, Flex Fare trips kept, zones 264/265 excluded from statistics.
- Every cell is stored; the minimum trip count is applied in the API (proposed 5, PO to confirm).
- Re-running the import replaces the statistics in one transaction.

**Tests:** none yet, no code this session.

**Next step:**
- Plan and build `import_trips` with Claude Code on branch `us0a-trip-import`: tests from the acceptance criteria first, then the code.
- Not blocked for coding. Moving US0a to Done needs the Integration deploy, which waits on AWS.

### 2026-10-16 — setup/django-scaffold (project setup, not a story)
**What changed:**
- Django project `taxiscope` + app `zones` scaffolded (Python 3.12 venv, Django 5.2.18).
- `requirements.txt` pinned: Django==5.2.18, django-environ==0.14.0, psycopg[binary]==3.3.6.
- Env-driven `taxiscope/settings.py` (django-environ, single `DATABASE_URL`); `.env.example` added, local `.env` created (gitignored).
- `.gitignore` added (`.venv/`, `.env`, caches, `*.sqlite3`, `staticfiles/`, top-level `/data/` and `*.parquet`, `.DS_Store`); previously-committed `.DS_Store` files untracked.
- Local Postgres 16 container `taxiscope-db` (port 5432) started; Django connection confirmed.
- Three tables added via `zones/models.py` + `zones/migrations/0001_initial.py`, matching the data model in CLAUDE.md/HLD: `Zone`, `ZoneHourStats`, `RouteHourStats`, with unique constraints and indexes on `(zone, day_of_week, hour)` and `(pickup_zone, dropoff_zone, day_of_week, hour)`. Ran `migrate`; verified the tables and constraints in `psql`.
- Map page added at `/`: `zones/templates/zones/map.html`, `zones/static/zones/js/map.js`, `zones/static/zones/css/map.css`, Leaflet 1.9.4 vendored into `zones/static/zones/vendor/leaflet/` (no CDN).
- Fixed OSM tile 403s: Django's default `Referrer-Policy: same-origin` was stripping the `Referer` header on cross-origin tile requests. Set `SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"` and added `referrerPolicy` to the Leaflet tile layer options.
- Tests added: `zones/tests/test_models.py` (Zone, ZoneHourStats save/read back), `zones/tests/test_views.py` (`GET /` returns 200 with `#map`).
- README: short "Run it locally" section.
- CLAUDE.md: added a `setup/*` branch-name exception for non-story work; documented the `day=` convention in the API section.

**Decisions made (also in `decisions.md`):**
- Project/app layout: one project `taxiscope`, one app `zones`.
- Python 3.12. Django 5.2 (LTS).
- Test runner: Django's built-in `manage.py test`, no pytest.
- `django-environ` with a single `DATABASE_URL`; `psycopg[binary]` (v3) as the driver.
- One env-driven `settings.py`, no settings split.
- Zone shapes file location: `zones/data/` (not covered by the `/data/` gitignore rule).
- Leaflet vendored into `zones/static/`, not loaded from a CDN.
- `day_of_week` convention: Monday=0 .. Sunday=6 (Python `weekday()` / pandas `dayofweek`), used in the DB columns and the API's `day=` parameter.
- Noted under Open/Risks: OpenStreetMap's public tile servers have a usage policy and aren't meant for heavy production use (one local 403 already); check before the sprint demo and be ready to switch tile providers.

**Tests:** `manage.py test` — 3 tests, OK. No CI configured yet (open item).

**Next step:**
- Split US0 (data import) into pieces of 3 points or less and start the first piece.
- Start US1 (#3, demand map): `GET /api/zones?day=&hour=` and wiring real zone data (shapes + stats) into the map page.
- Still open, needed soon: which AWS services host the app/DB (before first deploy), the minimum trip count for a window to show, the exact best/worst rule for travel windows, which TLC months to load first, and CI tooling.
- Nothing pushed yet; this branch (`setup/django-scaffold`) has not been opened as a PR.

### 2026-10-18 — us0b-zone-shapes (US0b, #21)
**What changed:**
- Downloaded the official TLC taxi zone shapefile (`https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip`, sha256 `f6d71191…5adf17`) outside the repo.
- Added `scripts/build_zone_shapes.py` (pyshp + pyproj). It reads the CRS from the `.prj` (found: NAD83 / New York Long Island (ftUS), EPSG:2263), converts to WGS84 [lon, lat], rounds to 6 decimals, does no simplification, checks that the LocationIDs are unique and exactly 1..263, then writes the file.
- Generated `zones/data/taxi_zones.geojson`: 263 features (240 Polygon, 23 MultiPolygon), properties `LocationID`, `zone`, `borough`, 2,275,317 bytes (2.17 MB). The ID check passed on the first run; the current shapefile no longer has the old duplicate IDs (56/57, 103/104/105).
- Added `zones/tests/test_zone_shapes.py` (SimpleTestCase, no DB or network): FeatureCollection shape, 263 unique IDs = 1..263, required properties and Polygon/MultiPolygon geometry, every coordinate inside an NYC lon/lat box.
- README: "Regenerate the zone shapes" section. `docs/decisions.md`: zone shapes section.
- pyshp 3.1.6 and pyproj 3.8.0 installed in the local `.venv` only. Not in `requirements.txt`.

**Decisions made (also in `decisions.md`):** shapefile source link, build tool and pinned versions, CRS read from `.prj`, output format and 6-decimal rounding, the 1..263 ID rule.

**Tests:** `manage.py test`, 7 tests, OK (3 existing + 4 new).

**Next step:**
- Acceptance criterion 3 (zones line up in Leaflet): **passed (2026-10-18).** The user checked it by eye on a throwaway Leaflet page (vendored Leaflet over OpenStreetMap, outside the repo). Zones line up with the streets at Central Park, the Manhattan edges, JFK, LaGuardia, Newark and Staten Island. Popups show the right ID, zone and borough. Mention this in the PR.
- US1 (#3): serve the shapes joined with `zone_hour_stats` from `GET /api/zones`. Load the file once at startup. At 2.2 MB, check the response size and consider gzip.
- Not pushed; the user does all the git.

### 2026-10-18 — us1-demand-map (US1, #3)
   **What changed:**
   - Added `GET /api/zones?day=&hour=` in `zones/views.py` and `zones/urls.py`. Returns all 263 zones as GeoJSON with `zone_id`, `name`, `borough`, `trip_count`. Defaults to the current NYC day and hour. Returns 400 for a bad day or hour.
   - Map page (`zones/static/zones/js/map.js`, `map.css`) colors zones by pickups in 5 groups, grey for no trips, with a legend and a hover box showing name, borough and pickups.

   **Decisions made (also in `decisions.md`):** default day/hour use NYC time; colors split zones into 5 equal-sized groups.

   **Tests:** new `zones/tests/test_zones_api.py`. `manage.py test`: 91 tests, OK.

   **Next step:** the response is about 2.5 MB; consider Django's `GZipMiddleware`. US4 (time filter) can reuse `/api/zones` with `day` and `hour`.
