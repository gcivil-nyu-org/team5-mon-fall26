# TaxiScope NYC (CS GY 6063, Team 5)

Web app that shows NYC riders historical taxi demand, fares, and trip duration by zone and day/hour, built from NYC TLC trip data. Epic 1 (Explore Zone Demand & Fares) is the current focus. It is read-only and needs no account.

## Source of truth (read these before coding a story)
- `docs/design/High-Level-Design.md`: components, data model, API, sequence diagrams (copy of the team wiki page)
- `docs/epic-1.md` and `docs/stories/`: Epic 1 and its user stories
- `docs/stories/README.md`: how the story files map to ZenHub issues; refresh with `scripts/sync-stories.sh`
- `docs/decisions.md`: decisions already made. Add to it, never contradict it silently
- `docs/progress.md`: what is done, what is next, handoff notes from the last session
- Team wiki (design, Definition of Ready, Definition of Done): https://github.com/gcivil-nyu-org/team5-mon-fall26/wiki

## Required by the course
- Language: Python. Project type: web application. Framework: Django. Hosting: AWS.
- Database: sqlite, PostgreSQL, or MySQL are all valid. Source control: git/GitHub. Project management: Scrum with ZenHub.
- Branching: `develop` (integration) and `main` (releases) in origin. Work on an individual branch, open a pull request into `develop`, a teammate reviews, approves, and merges. No direct pushes and no forced pushes to `develop` or `main`.
- `develop` deploys to the Integration instance. `main` deploys to the Production instance, tagged to match the ZenHub sprint milestone. The sprint demo runs only on Production.
- Estimates use planning poker with 0, 0.5, 1, 2, 3. Anything bigger is split.

## Our stack (decided in the High Level Design)
- Frontend: Django templates + Leaflet, calling the Django JSON endpoints (no separate React app)
- Database: PostgreSQL, no PostGIS. Zone shapes are a static GeoJSON file joined to the stats in Django
- Data import: a Django management command (pandas/pyarrow) that imports one monthly TLC Parquet file, cleans it, and writes the aggregate tables. No PySpark
- Open: which AWS services to use, the minimum trip count, the best/worst rule (see `docs/decisions.md`)

## Data model
- `zone(zone_id, name, borough)` (boundary shapes are in the GeoJSON file, keyed by `zone_id`)
- `zone_hour_stats(zone_id, day_of_week, hour, trip_count, avg_duration_min, fare_min, fare_avg, fare_max)`
- `route_hour_stats(pickup_zone_id, dropoff_zone_id, day_of_week, hour, trip_count, avg_duration_min, fare_min, fare_avg, fare_max)`

## API (Epic 1, all public and read-only)
- `GET /api/zones?day=&hour=`: zones as GeoJSON with trip volume (defaults to current day and hour)
- `GET /api/zones/:id/heatmap`: 7 x 24 trip volume and average duration
- `GET /api/routes?from=&to=&day=&hour=`: fare min/avg/max, typical duration, trip volume (`to` optional)
- `GET /api/routes/windows?from=&to=&day=`: hours of the day ranked, best and worst windows
- Too few trips: return an empty result and show "Not enough data"

## Stories (ZenHub issue numbers)
US1 #3 map, US2 #4 select zones, US3 #5 heatmap, US4 #6 time filter, US5 #7 fare range, US6 #8 duration, US7 #9 best/worst, US8 #10 trip summary, US9 #11 no account. The data pipeline story is being split into pieces of 3 points or less (numbers TBD).

## How to work
- One story per branch and per pull request. Branch name: `us<N>-short-name`. Target branch: `develop`. Exception: work that is not a user story (project setup, tooling, CI) uses `setup/short-name` instead.
- Start with a short plan, then write unit tests from the acceptance criteria, then the code.
- Do not add a dependency or change the API contract without saying so and updating the docs.
- A story is done only when it meets the Definition of Done on the wiki.
- Finish every session by appending a short note to `docs/progress.md`: what changed, decisions made, what is next.
