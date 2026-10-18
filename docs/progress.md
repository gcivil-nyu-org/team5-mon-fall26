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
