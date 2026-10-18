# Decisions

Add new decisions at the bottom with the date. Do not contradict one silently: change it here and say why.

## Required by the course (not ours to change)
- Python, web application, Django framework, AWS hosting, git/GitHub, Scrum with ZenHub.
- Two environments: **Integration** (deployed from `develop`) and **Production** (deployed from `main`, tagged to match the ZenHub sprint milestone). The sprint demo runs only on Production.
- Estimates use planning poker with 0, 0.5, 1, 2, 3. Anything bigger is split. The team estimates, not the PO or SM.

## Our choices (agreed in the High Level Design)
- **Frontend:** Django templates + Leaflet. No separate React app.
- **Database:** PostgreSQL. No PostGIS.
- **Zone shapes:** one static GeoJSON file in the repo, joined to the statistics by zone id in Django.
- **Data import:** a Django management command using pandas and pyarrow. It reads one monthly TLC Parquet file at a time. No PySpark.
- **Precompute:** the import writes aggregate tables (`zone`, `zone_hour_stats`, `route_hour_stats`). The API never queries raw trips.
- **Fare range:** minimum, average, and maximum, computed after outlier cleaning.
- **Duration only:** the data has no wait time, so we report trip duration, not waiting.
- **Too few trips:** the API returns an empty result and the UI shows "Not enough data".
- **API contract:** the four endpoints in the High Level Design, all public and read-only. Changing them needs a note here and an updated HLD.

## Our choices (project scaffold, 2026-10-16)
- **Project and app layout:** one Django project `taxiscope`, one app `zones`. The data model, views, and (for now) the API all live in `zones`; split into more apps later only if it earns its keep.
- **Python version:** 3.12. Documented in the README. Do not rely on 3.13-only features.
- **Django version:** 5.2 (LTS).
- **Test runner:** Django's built-in `manage.py test`. No pytest, to avoid an extra dependency the course has not asked for.
- **Env vars:** `django-environ`, one `DATABASE_URL` for the database connection. All other settings (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`) are also read from the environment via `.env`.
- **Postgres driver:** `psycopg[binary]` (v3).
- **Settings layout:** a single env-driven `taxiscope/settings.py`, no `settings/base.py` + `dev.py`/`prod.py` split.
- **Zone shapes file location:** `zones/data/`. `.gitignore` only ignores the top-level `/data/` directory and `*.parquet` files, not `zones/data/`, so the committed GeoJSON file is not accidentally excluded.
- **Leaflet delivery:** vendored into `zones/static/`, not loaded from a CDN, so the demo does not depend on outside network access.
- **`day_of_week` convention:** Monday=0 .. Sunday=6, the same as Python's `weekday()` and pandas' `dayofweek`. Used consistently in the database columns and in the API's `day=` parameter.

## Our choices (data import, US0a #20, 2026-10-17)
Backed by an analysis of the January to August 2026 yellow taxi files. The numbers below come from that analysis.

- **Trip data:** yellow taxi trip records only.
- **Months loaded:** March, April, and May 2026, combined. Why: the most trips of any 3-month window in 2026 (11.2M after cleaning); not summer, so it fits the commuter persona; and three months instead of one cut the share of trips in route cells with fewer than 5 trips from about 25% to about 13%.
- **Import command:** `python manage.py import_trips --month 2026-03 --month 2026-04 --month 2026-05`. It takes one or more months. It still reads one Parquet file at a time and combines the per-month totals, so memory use stays at one month. Files it does not have yet are downloaded into `data/raw/` (gitignored).
- **Fare column:** fare statistics use "fare before tip" = `total_amount - tip_amount`. Why: `fare_amount` is the meter fare only and leaves out surcharges, taxes, and the congestion fee (a median of $4.75 per trip). `total_amount` includes tips only for card payments, because cash tips are not recorded, so card and cash trips look different (median $21.94 vs $18.65, August 2026). Fare before tip makes them match ($18.90 vs $18.65).
- **Cleaning rules:** a trip is removed if any of these is true:
  - pickup time is outside the month of its file
  - `fare_amount <= 0` or fare before tip `<= 0`
  - fare before tip `> $500`
  - `trip_distance <= 0` or `> 100` miles
  - duration (dropoff minus pickup) `< 1` minute or `> 180` minutes
  - `payment_type` 6 (voided trip)
  - pickup or dropoff zone missing, or zone 264 or 265 (unknown / outside NYC)

  This removes 5 to 6.5% of trips per month, mostly zero-distance trips and trips under 1 minute.
- **Flex Fare trips are kept:** `payment_type` 0 ("Flex Fare trip" in the TLC data dictionary) is about a quarter of all trips. They are real, paid, upfront-priced trips.
- **Day and hour:** `day_of_week` and `hour` come from the pickup timestamp as recorded (NYC local time, no time zone conversion).
- **Pickup-based zone stats:** `zone_hour_stats` groups trips by pickup zone. `route_hour_stats` groups by pickup and dropoff zone pair.
- **Zone list:** `zone` is filled from the TLC taxi zone lookup CSV, committed in `zones/data/`. Zones 264 and 265 are loaded into `zone` but never appear in the statistics.
- **Every cell is stored:** the import keeps every day/hour cell, even with one trip. The minimum trip count is applied in the API (see Open), so it can change without re-importing.
- **Running the import again:** zones are updated in place, never deleted (deleting would cascade to the statistics). Both statistics tables are emptied and refilled inside one transaction. Running the same import twice gives the same rows, and if the import fails halfway the old data stays.
- **Import report:** for each month and in total: rows read, rows removed by each rule, rows kept. Then the number of zone and route cells, and how many have fewer than 5 trips.
- **New dependencies:** `pandas` and `pyarrow` (already named in the HLD). Downloads use Python's standard library, so no `requests`.

## Our choices (import_trips implementation, US0a #20, 2026-10-18)
- **Removed-trip counting:** each removed trip is counted once, under the first rule it fails, in this order: pickup outside month, voided, unknown zone, fare not positive, fare over $500, distance, duration. Why: the per-rule counts add up to rows removed, and a voided trip is reported as voided, not as "fare <= 0".
- **Unknown zone:** "zone missing" also covers a zone ID that is not in the lookup CSV. Why: such a trip cannot be stored (foreign key to zone).
- **Money in integer cents:** fare before tip is converted to integer cents once per trip. Fare min and max are exact cents. `fare_avg` is rounded half up to 2 decimals once, when the rows are written.
- **Replacing the statistics:** DELETE, not TRUNCATE, so the API keeps serving the old data while an import runs. The two stats tables are ANALYZEd after the commit.
- **Months in one run:** the statistics always hold exactly the months given in the last run. Running with fewer months replaces all statistics with just those months. The import report lists the months loaded.
- **Repeated `--month`:** giving the same month twice is an error (CommandError), so a month can never be counted twice.
- **numpy pinned:** `numpy==2.5.4` is pinned next to pandas and pyarrow. This is a pin of a package pandas already installs, not a new dependency. Why: an unpinned numpy could change on a later `pip install`.
- **Missing values:** a trip with a missing value in a field a rule checks is removed under that rule. A missing payment type is kept, because only type 6 (voided) is removed.

## Our choices (zone shapes, US0b, 2026-10-18)
- **Source:** the official TLC taxi zone shapefile, https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip (linked from the TLC Trip Record Data page).
- **Build tool:** `scripts/build_zone_shapes.py` using pyshp==3.1.6 and pyproj==3.8.0. Needed only to rebuild the file, so they are not in `requirements.txt`.
- **Coordinate system:** read from the shapefile's `.prj`, never assumed; converted to WGS84 [longitude, latitude] (EPSG:4326).
- **Output:** `zones/data/taxi_zones.geojson`, one feature per zone with `LocationID` (int), `zone`, `borough`. Coordinates rounded to 6 decimals (~10 cm), no simplification. Size: 2.17 MB.
- **IDs:** LocationIDs must be unique and exactly 1..263; the script stops otherwise. Zones 264 and 265 (Unknown / Outside of NYC) have no shape.

## Open (decide before the story that needs it)
- Which AWS services host the Django app and the database. Needed before the first deploy.
- Minimum trip count for a window to be shown. **Proposed: 5** (2026-10-17). With March to May loaded, cells under 5 trips hold about 0.1% of zone trips and 13% of route trips. Confirm with the PO before US5, US6, and US7.
- Exact rule for "best" and "worst" travel windows (volume only, or a mix with duration).
- ~~Which months of TLC data to load first.~~ Decided 2026-10-17: March to May 2026, see "Our choices (data import)" above.
- CI tooling. Waiting on the remaining course slides. (Testing tool is decided above: Django's built-in test runner.)
- Map tile provider for the demo. OpenStreetMap's public tile servers have a usage policy and are not meant for heavy production use (they already 403'd once locally over a missing Referer header). Check this before the sprint demo and be ready to switch to another tile provider (for example a paid provider, or self-hosted tiles) if it becomes a problem.