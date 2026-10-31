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
- ~~Which AWS services host the Django app and the database.~~ App: Elastic Beanstalk (see "Our choices (CD, setup/ci, 2026-10-27)"). The database is reached through `DATABASE_URL`.
- ~~Minimum trip count for a window to be shown.~~ Decided 2026-10-22: 5 trips, see "Our choices (fare range, US5 #7)" below.
- ~~Exact rule for "best" and "worst" travel windows.~~ Decided 2026-10-23, confirmed by the Product Owner (Shyam) 2026-10-25: fare and duration ranked separately, see "Our choices (best and worst times, US7 #9)" below.
- ~~Which months of TLC data to load first.~~ Decided 2026-10-17: March to May 2026, see "Our choices (data import)" above.
- ~~CI tooling.~~ Decided 2026-10-27: Travis CI + Coveralls, see "Our choices (CI, setup/ci)" below. (Testing tool is decided above: Django's built-in test runner.)
- HTTPS on the Integration and Production environments. Both are plain `http://` Elastic Beanstalk URLs, so sign-up and sign-in (US10, US11) would send passwords unencrypted. Needed before real users create accounts.
- Password reset by email ("Forgot password?"). Left for later (US12 #41): it needs an email service on AWS (for example Amazon SES) and its credentials in Elastic Beanstalk. Until then, a user who forgets their password cannot get back in.
- Map tile provider for the demo. OpenStreetMap's public tile servers have a usage policy and are not meant for heavy production use (they already 403'd once locally over a missing Referer header). Check this before the sprint demo and be ready to switch to another tile provider (for example a paid provider, or self-hosted tiles) if it becomes a problem.

## Our choices (demand map, US1 #3, 2026-10-18)
- **Default day and hour:** `/api/zones` uses the current NYC day and hour when none is given, because trip times are recorded in NYC time.
- **Map colors:** zones with trips are split into 5 equal-sized groups by pickup count (yellow = quiet, dark red = busy). Zones with no trips are grey.

## Our choices (time filters, US4 #6, 2026-10-19)
- **Filter defaults:** use the current NYC weekday and hour for the controls and first map request.
- **Selected-zone summary:** selecting a zone shows its fare range and average duration. Changing the filters refreshes the summary with the map; zones without statistics show "Not enough data".
- **Zone API fields:** each zone includes its fare minimum, average, maximum, and average duration alongside its trip count.

## Our choices (fare range, US5 #7, 2026-10-22)
- **Minimum trip count:** 5 trips (team decision, 2026-10-22; confirmed by the Product Owner (Shyam) 2026-10-25). One setting, `MIN_TRIP_COUNT = 5` in `settings.py`, shared by US5, US6 and US7. It is applied in the API; the import still stores every cell.
- **`/api/routes` response:** always HTTP 200 for valid parameters, with the keys `from, to, day, hour, enough_data, trip_count, fare_min, fare_avg, fare_max, avg_duration_min`. If there is no row or `trip_count < MIN_TRIP_COUNT`, then `enough_data` is false, `trip_count` is the real count (0 if no row) and the four stats are null. This is how "the API returns an empty result" (HLD decisions above) is done for this endpoint: the stats are empty, and the count stays so the UI can explain it.
- **Which table:** with `to`, `route_hour_stats` only. A sparse route never falls back to the pickup zone's numbers. Without `to` (or with `to` empty), `zone_hour_stats` for the pickup zone: all trips from that zone.
- **`from == to`** (a trip within one zone) is a valid route.
- **Validation:** `from` is required. Day 0-6 (Monday=0) and hour 0-23 default to the current NYC time. A missing, non-integer or unknown zone id, or a bad day or hour, gives 400. Why 400 and not 404: the endpoint exists and only a query parameter is wrong, the same as `day=7`. The heatmap's 404 is for an id in the path.
- **Money in JSON:** fares are strings with two decimals (Django's encoder for `Decimal`), as in `/api/zones`. `fare_avg` is the stored value, never recomputed.
- **`/api/zones` is unchanged:** it still returns each zone's fare and duration with no minimum trip count (US4). The selection panel's fare line now reads `/api/routes` and is labeled "fare before tip". The duration line still reads `/api/zones` until US6. This replaces the fare part of the US4 "Selected-zone summary" decision.
- **Refresh timing:** the fare refreshes when the zones change, and when the map has loaded a new day or hour. A newer request always wins over an older response.
- **Trip within one zone (UI, 2026-10-23):** a "Trip within this zone" button in the selection panel, shown only when a pickup is selected and there is no dropoff, sets the dropoff to the pickup zone (`from == to`, already valid in `/api/routes`). The US2 click rules are unchanged: clicking the pickup clears everything, clicking another zone sets or replaces the dropoff. The panel shows "Dropoff: same zone"; its × returns to pickup only. The fare scope line reads "Trips within this zone" (a one-line change in `fare.js`). On the map the zone keeps the pickup border (blue, thicker) with a dashed dropoff-green border drawn on top, in its own non-clickable Leaflet pane so hovering never hides it. No new colors. `windows.js` and `heatmap.js` are unchanged; they react to the usual `taxiscope:zones-selected` event.

## Our choices (trip duration, US6 #8, 2026-10-23)
- **Duration line reads `/api/routes`, not `/api/zones`:** the duration line now comes from the same `avg_duration_min` and `enough_data` as the fare line, instead of the pickup zone's duration from `/api/zones` (which ignored `MIN_TRIP_COUNT` and a selected dropoff). This is the fix for the fare/duration mismatch Aleena flagged in the US5 notes.
- **One response, one file:** `fare.js` writes both the fare line and the duration line from the single `/api/routes` fetch it already makes, in the same `enough_data` branch, so the two lines are never computed from different responses. `filters.js` no longer writes the duration line. No new endpoint, no API contract change.

## Our choices (best and worst times, US7 #9, 2026-10-23)
- **Rule (confirmed by the Product Owner (Shyam), 2026-10-25):** the story's own example, "lowest/highest fare and duration". The hours of the selected day are ranked twice, once by average fare and once by average duration. Best = the cheapest hour and the fastest hour. Worst = the most expensive hour and the slowest hour. No combined score, so no weighting to agree on, and every result can be checked against one column of the data. Why not one score: on real data the most expensive and the slowest hour are often different (Upper East Side South -> North, Wednesday: most expensive 16:00, slowest 15:00).
- **A window is one hour** (`H:00–H:59`), the grain of the stats tables.
- **Which hours count:** only hours with at least `MIN_TRIP_COUNT` (5) trips, the same rule as US5 and US6. Fewer than 2 such hours on that day gives `enough_data` false and no best or worst.
- **Ties:** the earlier hour wins, for best and for worst.
- **Which table:** the same as `/api/routes`: with `to`, `route_hour_stats` for that route; without `to`, `zone_hour_stats` for all trips from the pickup zone.
- **Labeled as historical:** the UI says the times come from past trips (March to May 2026) and are not a guarantee.
- **`/api/routes/windows` response:** always HTTP 200 for valid parameters, with the keys `from, to, day, enough_data, hours, by_fare, by_duration, best, worst`. `hours` lists the qualifying hours in hour order, each with `hour, trip_count, fare_avg, avg_duration_min`. `by_fare` and `by_duration` are the same hours as hour numbers, cheapest or fastest first. `best` and `worst` each hold `fare` and `duration`, one hour object each. Not enough data: `hours`, `by_fare`, `by_duration` empty and `best`, `worst` null. Validation is the same as `/api/routes` (400 for a missing, non-integer or unknown zone, or a day outside 0-6); `day` defaults to the current NYC day. No `hour` parameter: the windows cover the whole day.
- **UI:** a "Best and worst times" section in the selection panel (`windows.js`). Best rows are green, worst rows red, each with a "Best" or "Worst" tag. It reloads when the zones or the day change, not the hour.
- **Only for a trip (team decision, 2026-10-23):** the section shows only once both a pickup and a dropoff are selected. The story is about "my trip", and pickup-only results mix every destination. The API still accepts a missing `to` (all trips from the pickup zone), but the UI does not use it.

## Our choices (trip summary, US8 #10, 2026-10-23)
- **One summary in the selection panel:** The collapsible trip summary sits directly below pickup and dropoff. It replaces the separate fare/duration lines, US7 windows section, and floating summary so each result appears once.
- **Data sources and ownership:** `fare.js` supplies fare and duration from `/api/routes`; `windows.js` supplies US7's `best.fare`, `best.duration`, `worst.fare`, and `worst.duration` from `/api/routes/windows`. Both write into the shared panel managed by `trip-summary.js`. The API contracts and US7 ranking calculation are unchanged. US7's ranking rule still awaits PO confirmation.
- **Pickup-only and route views:** Selecting a pickup expands the summary with zone-wide fare and duration from `/api/routes` without `to`. Selecting a dropoff expands it with route fare, duration, and best/worst rows. The best/worst rows stay hidden without a dropoff, as agreed for US7. A disclosure button collapses and reopens the summary; clearing the pickup hides it.
- **Refresh and missing data:** Zone changes refresh immediately. Time changes refresh only after the map confirms the new day and hour. Responses with too few trips show "Not enough data"; failed requests show a separate error.

## Our choices (use without an account, US9 #11, 2026-10-25)
- US9: map tiles load from OpenStreetMap, which sees visitor IPs; hosting access logs also record IPs; the app itself stores no personal data.

## Our choices (CI, setup/ci, 2026-10-27)
- **CI tooling (decided, closing the "CI tooling" item under Open):** Travis CI (`app.travis-ci.com`), coverage uploaded to Coveralls. No deploy step yet; that is added separately once AWS hosting is decided.
- **Formatting and linting:** black (line length 88, the default) and flake8, configured to agree (`.flake8` sets `max-line-length = 88` and ignores `E203`, which black and flake8 disagree on for slice spacing). `requirements-dev.txt` adds black, flake8, coverage, and coveralls on top of `requirements.txt`.
- **PostgreSQL on Travis:** `dist: jammy`, version 14 (the version bundled with that image). PostgreSQL 16 is not available on `jammy` — it needs `dist: noble`, which this project does not use, so the minimum-trip-count-style "prefer newest, else the closest available" rule picked 14. The app has no version-specific PostgreSQL features, so this does not affect behavior.
- **Coverage scope:** `.coveragerc` measures the project's own code (`source = .`), omitting virtualenvs, migrations, tests, `manage.py`, `wsgi.py`, `asgi.py`, and `scripts/` (one-off tooling, not part of the deployed app, not imported by it).
- **Minimum coverage:** no enforced threshold in CI yet (the course asked for 85%+ as a one-time check, not a gate). The project's own code is at 100% as of this setup (`zones/models.py`'s `__str__` methods were the only gap, now tested in `test_models.py`).
- **Secrets:** `.travis.yml`'s `SECRET_KEY` and `DATABASE_URL` are CI-only dummy values with no access to anything real; Coveralls' upload token is not stored anywhere — the `coveralls` CLI reads it from Travis's own build environment. See `docs/ci.md`.

## Our choices (CD, setup/ci, 2026-10-27)
- **Hosting:** AWS Elastic Beanstalk, application `taxiscope`, region `us-east-2`, Python 3.14 on Amazon Linux 2023. Integration is `Taxiscope-integration-env` and Production is `taxiscope-env`. This replaces "No deploy step yet" in the CI entry above.
- **Deploy tool:** Travis dpl v2 (`edge: true`), provider `elasticbeanstalk`. `develop` deploys to Integration and `main` to Production, with `wait_until_deployed: true`. Pull requests never deploy. Cron builds are skipped (`condition: "$TRAVIS_EVENT_TYPE != cron"`). AWS keys are hidden Travis repository settings only.
- **Deploy files in git:** `Procfile` (gunicorn) and `.ebextensions/01_static.config`, copied unchanged from the bundle production was first deployed with. `STATIC_ROOT = BASE_DIR / "staticfiles"` is in settings and the Elastic Beanstalk proxy serves `/static`, so no whitenoise.
- **Migrate and collectstatic:** `.ebextensions/02_django.config` `container_commands` (migrate `leader_only`), not the bundle's `.platform/hooks` scripts. Travis builds its own zip, and hooks only run if executable, so they could be skipped silently.
- **New dependency:** `gunicorn==26.2.0` in `requirements.txt`. The Procfile uses it, and before this it came only from the platform.
- **Release rule:** nobody merges into `main` unless the latest `develop` deploy to Integration succeeded.

## Our choices (sign up, US10 #39, 2026-10-27)
- **User model:** Django's built-in `User` (`django.contrib.auth`), no custom model. New `accounts` app for the account pages, mounted at `/accounts/`.
- **Email as the sign-in name:** the email, trimmed and lowercased, is stored in both `username` and `email`. `username` is unique, so one account per email, and Django's username-based sign-in (US11) works unchanged. `Alex@Example.com` and `alex@example.com` are the same account. Max length 150 (the `username` limit).
- **Password rules:** the `AUTH_PASSWORD_VALIDATORS` already in `settings.py` (similar to the email, at least 8 characters, not common, not all numbers). The form shows every reason that applies. A "Confirm password" field catches typos.
- **Email already registered:** "An account with this email already exists." This says the email has an account, which a sign-up form cannot avoid. Sign-in (US11) uses one generic error instead. Two sign-ups with the same email at the same moment: the unique `username` makes the second fail, and it gets the same message.
- **After sign-up:** the user is signed in and sent to the map. A signed-in user who opens the sign-up page goes to the map.
- **Header:** guests see "Sign up" on the right of the map header; signed-in users see their email. Same line as the title, so the header height and the map are unchanged. The map and every Epic 1 API stay public (US9).


## Our choices (sign in and sign out, US11 #40, 2026-10-27)
- **Django's auth views:** `LoginView` at `/accounts/signin/` and `LogoutView` at `/accounts/signout/`. `LOGIN_URL = "accounts:signin"`, `LOGIN_REDIRECT_URL` and `LOGOUT_REDIRECT_URL` are the map.
- **Email to sign in:** `SignInForm` is Django's `AuthenticationForm` with the field labeled "Email", trimmed and lowercased to match how US10 stores it.
- **One generic error:** an unknown email, a wrong password and an inactive account all show "The email or password is incorrect.", so sign-in never says whether an email has an account. (Sign-up still has to say "already exists", see US10.)
- **Sign out is a POST:** a small form with a CSRF token, styled like a link in the header. A GET does not sign out (Django 5 `LogoutView` answers 405), so a link on another site cannot sign a user out.
- **Pages that need an account:** decorate the view with `@login_required`. A guest goes to `/accounts/signin/?next=<page>` and comes back after signing in; `next` pointing to another site is ignored (Django checks it). The first such page is a minimal "My account" at `/accounts/account/`, which US12 extends; "My routes" (US13) and "My plans" (US17) should use the same decorator.
- **CSRF on every form:** Django's `CsrfViewMiddleware` (on by default) plus tests that the middleware stays on and that every `method="post"` form in the templates has `{% csrf_token %}`.
- **Header:** guests see "Sign in" and "Sign up"; signed-in users see their email (links to My account) and "Sign out". One line, so the map height is unchanged.
- **Not in scope:** limiting repeated wrong passwords (rate limiting) and "remember me". Both can be added later without changing the above.

## Our choices (manage and delete my account, US12 #41, 2026-10-27)
- **My account page** (`/accounts/account/`, sign-in required): shows the email, "Sign out", a change-password form and a link to delete the account.
- **Change password:** Django's `PasswordChangeView` and `PasswordChangeForm`: current password, new password twice, checked by the same `AUTH_PASSWORD_VALIDATORS` as sign-up. The user stays signed in on this device afterwards (Django updates the session hash) and sees "Your password was changed." Other devices are signed out, because their sessions no longer match.
- **Delete account:** `/accounts/account/delete/` explains that the account and everything saved in it are deleted, and the user confirms by entering their password. A wrong password deletes nothing. On success the user row is deleted, the user is signed out and sent to the map. The email can no longer sign in, but can sign up again as a new account.
- **Delete before sign-out:** the account is deleted first, then the session is ended, so a failed delete never leaves the user signed out with the account still there.
- **Everything saved is deleted with the account:** every `ForeignKey` or `OneToOneField` to the user must use `on_delete=models.CASCADE`. A Django system check (`accounts.E001`, `accounts/checks.py`) reports any link without it, at `manage.py check`, `runserver`, `migrate` (also on deploy) and in the tests. Saved routes (US13) and plans (US17) do not exist yet; their models must follow this.
- **Password reset by email:** not built yet, because it needs an email service on AWS. Listed under "Open" above.

## Our choices (save a route, US13 #42, 2026-10-28)
- SavedRoute belongs to the authenticated user, with a name, pickup, dropoff and creation time. The user and zone relationships use CASCADE; deleting an account deletes its routes.
- Names are trimmed, required, limited to 50 characters and unique per user (case-sensitive). A database constraint protects against simultaneous duplicate saves. Different users may reuse the same name.
- The map shows the save form only when a signed-in user selects both zones. Trips within one zone are valid. Guests see a sign-in prompt when both zones are selected.
- New endpoint: CSRF-protected POST /saved-routes/save/ accepts form fields name, pickup_zone and dropoff_zone. Ownership always comes from the session. Success returns 201 with id and name; invalid input returns 400 with field errors; an expired/guest session returns 401 with a sign-in prompt. Other methods return 405. Existing public statistics APIs remain unchanged.
- US13 returns only the newly created route to its owner. The private list, open, rename and delete flows are US14.

## Our choices (manage saved routes, US14 #43, 2026-10-28)
- Saved-route models, forms, views, URL names, templates and page styling belong to the separate routes Django app. It reads Django's login state; account management remains in accounts. State-only migrations move the model label from zones to routes while retaining the existing zones_savedroute table, data and unique constraint.
- My routes is a sign-in-only page at /saved-routes/. It lists only the current user's routes, with name, pickup, dropoff and save date. The map header links to it as Routes, including for guests who are redirected to sign-in.
- Open uses GET /saved-routes/<id>/open/ to render the existing map. The server verifies ownership before rendering; after the map loads, the saved zone ids drive the existing taxiscope:zones-selected event so the trip summary opens.
- Rename uses GET/POST /saved-routes/<id>/rename/ and the same trimmed, required, 50-character, per-user unique name rules as US13. Renaming to the current name is allowed.
- Delete uses GET/POST /saved-routes/<id>/delete/. GET shows a confirmation page; POST with CSRF protection deletes the route. Unknown or other users' route ids return 404 for open, rename and delete.

## Our choices (leave-by suggestion, US15 #44, 2026-10-28)
- The public GET /api/routes/leave-by endpoint requires known pickup and dropoff zone ids, a Monday=0 day (0-6), and an HH:MM arrival time on a 15-minute boundary. Invalid requests return 400. It reads the existing route_hour_stats through the shared route statistics query.
- Start with the arrival hour's average duration. Subtract it to select the estimated departure day and hour, then subtract that hour's average duration once more. Round the result down to the previous 15-minute boundary; day arithmetic wraps across midnight and Sunday/Monday.
- The response provides the leave day/time, typical journey duration and average fare for the departure hour. If either required hour has fewer than MIN_TRIP_COUNT trips, it returns enough_data false and null estimates.
- An Arrive by form appears under the trip summary when both zones are selected. It displays the result or Not enough data and labels the result an estimate from March to May 2026 trips, not a guarantee.

## Our choices (cheapest in the next 3 hours, US16 #45, 2026-10-30)
- **New endpoint:** public `GET /api/routes/cheapest?from=&to=&day=&start=HH:MM`. `from` and `to` must be known zone ids and `day` 0-6 (Monday=0), the same checks as `/api/routes/leave-by`; invalid requests return 400. It reads `route_hour_stats` through the shared `route_stats` query.
- **Start time:** `start` accepts any `HH:MM`, not only quarter hours, so "Now" can use the exact current New York time. The custom start time picker moves in 15-minute steps. ("Arrive by" still requires quarter hours.)
- **Now:** the browser computes the current day and time with the `America/New_York` time zone, so it is New York time wherever the rider is.
- **Window:** the start hour and the next 2 hours. Past midnight it continues into the next day; Sunday 23:00 continues into Monday.
- **Rule:** only hours with at least `MIN_TRIP_COUNT` trips are compared. The lowest average fare wins; on a tie, the earlier hour wins.
- **Suggestion:** leave at the start time if the first hour is cheapest, otherwise at the start of the cheapest hour. Expected arrival = departure + that hour's average duration, rounded to the minute, with day wrap.
- **No data:** sparse hours show "Not enough data"; if none of the 3 qualifies, the response has `enough_data` false and the page says so.
