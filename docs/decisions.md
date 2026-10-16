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

## Open (decide before the story that needs it)
- Which AWS services host the Django app and the database. Needed before the first deploy.
- Minimum trip count for a window to be shown (suggested starting point: decide with the PO).
- Exact rule for "best" and "worst" travel windows (volume only, or a mix with duration).
- Which months of TLC data to load first.
- CI and testing tools. Waiting on the remaining course slides.
