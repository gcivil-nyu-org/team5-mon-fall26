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
