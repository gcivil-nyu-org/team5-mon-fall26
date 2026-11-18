# TaxiScope NYC (CS GY 6063, Team 5)

Web app that shows NYC riders historical taxi demand, fares, and trip duration by zone and day/hour, built from NYC TLC trip data. Epic 1 (Explore Zone Demand & Fares) is the current focus. It is read-only and needs no account.

## Source of truth (read these before coding a story)
- `docs/design/High-Level-Design.md`: components, data model, API, sequence diagrams (copy of the team wiki page)
- `docs/epic-1.md` and `docs/stories/`: Epic 1 and its user stories
- `docs/stories/README.md`: how the story files map to ZenHub issues; refresh with `scripts/sync-stories.sh`
- `docs/decisions.md`: decisions already made. Add to it, never contradict it silently
- `docs/progress.md`: what is done, what is next, handoff notes from the last session
- `docs/accounts.md`: rules for stories that store user data (on_delete=CASCADE, @login_required, CSRF)
- `docs/ci.md`: the Travis CI pipeline and the Elastic Beanstalk deploys
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
- Data import: a Django management command (pandas/pyarrow) that imports one or more monthly TLC Parquet files (one file at a time), cleans them, and writes the aggregate tables. No PySpark
- Hosting: AWS Elastic Beanstalk with RDS PostgreSQL, region us-east-2. Integration env `Taxiscope-integration-env` (from `develop`), Production env `taxiscope-env` (from `main`)
- CI/CD: Travis CI + Coveralls. Travis runs black, flake8, the Django and Node tests, and deploys `develop` and `main` to Elastic Beanstalk. See `docs/ci.md`
- Open: the minimum trip count (proposed 5), the best/worst rule (see `docs/decisions.md`)

## Data model
- `zone(zone_id, name, borough)` (boundary shapes are in the GeoJSON file, keyed by `zone_id`)
- `zone_hour_stats(zone_id, day_of_week, hour, trip_count, avg_duration_min, fare_min, fare_avg, fare_max)`
- `route_hour_stats(pickup_zone_id, dropoff_zone_id, day_of_week, hour, trip_count, avg_duration_min, fare_min, fare_avg, fare_max)`
- Epic 4: `accounts_profile(user_id, display_name)`, one per user, unique ignoring capitals (US30 #92). Other riders only ever see the display name, never the email.
- Epic 4: `rides_ridepost(owner_id, pickup_zone_id, dropoff_zone_id, departure_at, seats, note, status, created_at)` (US31 #93). Status `open`/`full`/`closed`/`deleted`; "Expired" is worked out when read (`RidePost.objects.open()`). US32 #94: `/rides/` finds open posts on the same or adjacent zones (`rides/search.py`). The owner manages a post's interested riders on `/rides/<id>/`; other riders can view it while open or after showing interest, unless deleted.
- Epic 4: `rides_rideinterest(post_id, rider_id, status, created_at)` (US33 #95), one per rider per post; status `pending`/`accepted`/`declined`. `POST /rides/<id>/interest/` and `/withdraw/`. US34 #96 adds owner-only accept, decline and undo-acceptance actions; accepted riders consume seats, filling and reopening a post as capacity changes.
- US35 #97 lets the owner edit an open post, close it, or mark it deleted after confirmation. Deleted posts return 404 on detail pages; their interest rows remain so riders can see a deletion notice in the shared-rides list.
- Epic 4: `rides_ridemessage(post_id, sender_id, receiver_id, text, sent_at, read_at)` (US36 #98). A conversation is a post plus its owner and one interested rider: `/rides/<id>/messages/<rider-id>/` (page and send) and `/new/?after=<message-id>` (JSON, polled every 15 seconds while visible). 404 for anyone else. Read-only 24 hours after departure or once the post is deleted; 30 messages per sender per hour (`rides/messaging.py`).
- Epic 4: US37 #99 `/rides/mine/` ("My rides", `rides/my_rides.py`): the user's posts and the rides they asked to join, unread counts per conversation, rides more than 7 days old hidden unless `?past=1`. `rides_rideinterest.owner_seen_at` (empty = new interested rider) is set when the owner opens the post page. The nav badge (unread + new riders) comes from the `rides.context_processors.ride_badge` context processor.
- Epic 4: `rides_contentreport(reporter_id, post_id, message_id, reason, note, reported_text, status, created_at)` (US38 #101), exactly one of post or message, one per reporter per item. `/rides/<id>/report/` and `/rides/messages/<message-id>/report/` (`rides/reporting.py`); 404 for own content. Admins check reports in the Django admin; the reported rider never sees who reported them.

## Admin (US39 #113)
- Django admin at `/admin/`, staff only (active + `is_staff`). Staff accounts: `manage.py create_staff` (password asked in the terminal, never an option) and `manage.py remove_staff --email`. Never put a real staff email, username or password in the repo.
- The "Admin" header link is `accounts/templates/accounts/_admin_link.html`. The Accounts admin (`accounts/admin.py`) never shows passwords and keeps staff rights read-only. Read-only tables use `zones.admin.ReadOnlyModelAdmin` (Zone now, ImportRun in US40).
- US40 #114: `zones_importrun` (`zones.ImportRun`) records every `import_trips` / `import_rideshare` run (who: `--by` or the OS user; status running/succeeded/failed; the report's totals and text; the error). Saved by `zones/importer/history.py` outside the import's transaction, so a failed run is still recorded. Read-only "Import history" in the admin.
- `accounts/tests/test_admin_access.py` checks every admin URL refuses guests and riders; a new registered model is covered automatically.
- The AWS sites are HTTP only: staff must not sign in to the admin on Production (or Integration) until HTTPS is enabled.

## API (Epic 1, all public and read-only)
- `GET /api/zones?day=&hour=`: zones as GeoJSON with trip volume (defaults to current day and hour)
- `GET /api/zones/:id/heatmap`: 7 x 24 trip volume and average duration
- `GET /api/zones/:id/surge`: 7 x 24 likely Uber/Lyft surge hours, with fare per mile and average wait (US29 #76; rule in `docs/decisions.md`)
- `GET /api/routes?from=&to=&day=&hour=`: fare min/avg/max, typical duration, trip volume (`to` optional)
- `GET /api/routes/windows?from=&to=&day=`: hours of the day ranked, best and worst windows
- `GET /api/routes/rideshare?from=&to=&day=&hour=`: the Uber/Lyft twin of `/api/routes` (same validation and `enough_data` rule) plus `avg_wait_min` (US28 #75)
- Too few trips (fewer than MIN_TRIP_COUNT = 5 in settings.py): the API returns 200 with "enough_data": false and null stats, and the UI shows "Not enough data"
- `day=` convention: Monday=0 .. Sunday=6, the same as Python's `weekday()` and pandas' `dayofweek`. Same convention in the database's `day_of_week` columns.

## Stories (ZenHub issue numbers)
US1 #3 map, US2 #4 select zones, US3 #5 heatmap, US4 #6 time filter, US5 #7 fare range, US6 #8 duration, US7 #9 best/worst, US8 #10 trip summary, US9 #11 no account. The data pipeline story US0 #16 is split into US0a #20 (trip import and stats) and US0b #21 (zone shapes).

## How to work
- One story per branch and per pull request. Branch name: `us<N>-short-name`. Target branch: `develop`. Exception: work that is not a user story (project setup, tooling, CI) uses `setup/short-name` instead.
- Start with a short plan, then write unit tests from the acceptance criteria, then the code.
- Do not add a dependency or change the API contract without saying so and updating the docs.
- A story is done only when it meets the Definition of Done on the wiki.
- Finish every session by appending a short note to `docs/progress.md`: what changed, decisions made, what is next.
