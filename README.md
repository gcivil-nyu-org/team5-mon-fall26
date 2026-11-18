# team5-mon-fall26

| Branch | Build | Coverage | Environment |
|---|---|---|---|
| `develop` | [![Build Status (develop)](https://app.travis-ci.com/gcivil-nyu-org/team5-mon-fall26.svg?branch=develop)](https://app.travis-ci.com/gcivil-nyu-org/team5-mon-fall26) | [![Coverage Status (develop)](https://coveralls.io/repos/github/gcivil-nyu-org/team5-mon-fall26/badge.svg?branch=develop)](https://coveralls.io/github/gcivil-nyu-org/team5-mon-fall26?branch=develop) | [Integration](http://taxiscope-integration-env.eba-gfaktp8z.us-east-2.elasticbeanstalk.com/) |
| `main` | [![Build Status (main)](https://app.travis-ci.com/gcivil-nyu-org/team5-mon-fall26.svg?branch=main)](https://app.travis-ci.com/gcivil-nyu-org/team5-mon-fall26) | [![Coverage Status (main)](https://coveralls.io/repos/github/gcivil-nyu-org/team5-mon-fall26/badge.svg?branch=main)](https://coveralls.io/github/gcivil-nyu-org/team5-mon-fall26?branch=main) | [Production](http://taxiscope-env.eba-gfaktp8z.us-east-2.elasticbeanstalk.com/) |

TaxiScope NYC. See `CLAUDE.md` and `docs/` for the project docs.

## Run it locally

Requires Python 3.12 and a running PostgreSQL (e.g. the `taxiscope-db` Docker container).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in DATABASE_URL etc.
python manage.py migrate
python manage.py runserver
```

Run tests with:

```bash
python manage.py test
```

The frontend's JavaScript has its own tests, run with Node (requires no install — Node's built-in test runner):

```bash
node --test zones/tests/trip_summary.test.js
for f in zones/static/zones/js/*.js; do node --check "$f" || break; done   # syntax-check all the JS
```

## Regenerate the zone shapes

`zones/data/taxi_zones.geojson` is committed, so you only need this if TLC publishes new zone boundaries. It is built from the official TLC taxi zone shapefile by `scripts/build_zone_shapes.py`.

The script needs two packages that the app does not use, so they are not in `requirements.txt`. Install these exact versions:

```bash
pip install pyshp==3.1.6 pyproj==3.8.0
```

Download and unzip the shapefile outside the repo (this link is the "Taxi Zone Shapefile" link on the [TLC Trip Record Data page](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)), then run the script from the repo root:

```bash
mkdir -p ~/Downloads/taxi_zones && cd ~/Downloads/taxi_zones
curl -fLO https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip && unzip taxi_zones.zip
cd -   # back to the repo root
python scripts/build_zone_shapes.py ~/Downloads/taxi_zones/taxi_zones/taxi_zones.shp
python manage.py test zones.tests.test_zone_shapes
```

The script reads the coordinate system from the `.prj` file, converts to WGS84 longitude/latitude, rounds to 6 decimals, and writes one feature per zone (`LocationID`, `zone`, `borough`). It stops without writing anything if the LocationIDs are not unique and exactly 1..263. See `docs/decisions.md` (zone shapes).
## Import the trip data

```bash
python manage.py import_trips --month 2026-03 --month 2026-04 --month 2026-05
```

Downloads any missing monthly file into `data/raw/` (about 65 MB each, gitignored), then replaces all statistics in one transaction. Re-running is safe. Running it with fewer months replaces the statistics with just those months. At the end it prints a report: rows read, removed per cleaning rule, and kept, for each month and in total.

For the three months above it takes about 1.5 minutes and up to about 1.2 GB of memory (measured on a laptop against a local PostgreSQL).

## Import the rideshare data

```bash
python manage.py import_rideshare --month 2026-03 --month 2026-04 --month 2026-05
```

Imports the TLC High Volume For-Hire Vehicle files (Uber and Lyft combined, `fhvhv_tripdata_YYYY-MM.parquet`, about 530 MB each, gitignored) into `rideshare_zone_hour_stats` and `rideshare_route_hour_stats`. Options and behaviour match `import_trips`: `--month` is repeatable (giving the same month twice is an error), `--data-dir` defaults to `data/raw/`, missing files are downloaded first, and the two rideshare tables are replaced in one transaction, so re-running is safe, a failed run leaves the old data in place, and running with fewer months replaces the statistics with just those months. The taxi tables are not touched. The report gives, for each month and in total, rows read, removed per cleaning rule, kept, and waits left out of the wait average, then the zone and route cell counts and how many have fewer than `MIN_TRIP_COUNT` trips. The rules and choices are in `docs/decisions.md` ("Rideshare import").

For the three months above it takes about 2.5 minutes and up to about 2 GB of resident memory (measured on a laptop against a local PostgreSQL; see `docs/decisions.md`, US27d). The route table is about 730 MB on disk.

## Load the rideshare data into the shared AWS database

Integration and Production use the same RDS database, so this is done once, from a laptop, not on Elastic Beanstalk. Do it only when all of these are true:

- The `0004_rideshare_stats` migration has reached the shared database: the US27 pull requests are merged into `develop` and the Integration deploy (which runs `migrate`) succeeded. Check with `python manage.py showmigrations zones` against the RDS database (step 2): `[X] 0004_rideshare_stats`.
- The laptop has about 2.5 GB of free RAM (4 GB to be safe) and the three files are in `data/raw/` (otherwise the command downloads 1.6 GB first).
- The RDS instance is reachable from outside its VPC (RDS → Databases → the instance → Connectivity & security: "Publicly accessible: Yes"). If it is not, opening the security group is not enough; ask the team before changing it.
- It is a quiet time: the site reads the same database, and the replace uses its I/O and briefly locks the two rideshare tables (nothing reads them yet).

1. **Allow your IP on port 5432**, in the `taxiscope-db-sg` security group (us-east-2). In the console: EC2 → Security Groups → `taxiscope-db-sg` → Edit inbound rules → add PostgreSQL, TCP 5432, source "My IP". Or with the AWS CLI:

   ```bash
   SG=$(aws ec2 describe-security-groups --region us-east-2 \
        --filters Name=group-name,Values=taxiscope-db-sg \
        --query 'SecurityGroups[0].GroupId' --output text)
   MYIP=$(curl -s https://checkip.amazonaws.com)
   aws ec2 authorize-security-group-ingress --region us-east-2 \
       --group-id "$SG" --protocol tcp --port 5432 --cidr "$MYIP/32"
   ```

2. **Point Django at RDS in this shell only.** Take the value of the `DATABASE_URL` environment property of `Taxiscope-integration-env` (Elastic Beanstalk → Configuration → Updates, monitoring, and logging → Environment properties). Never write it to `.env` or any other file. A variable set in the shell wins over `.env`, which `settings.py` reads without overwriting:

   ```bash
   read -rs DATABASE_URL && export DATABASE_URL   # paste, then Enter; not echoed or kept in history
   python manage.py showmigrations zones          # must show [X] 0004_rideshare_stats
   ```

3. **Run the import** (about 2.5 minutes locally; longer over the internet, since about 4.6M rows are sent with COPY):

   ```bash
   python manage.py import_rideshare --month 2026-03 --month 2026-04 --month 2026-05
   ```

   Keep the report for the pull request or the sprint notes.

4. **Check the row counts** against the report (the trip counts in each table add up to the "Rows kept" total, 61,076,010 for March to May 2026; 43,185 zone cells and 4,524,149 route cells):

   ```bash
   python manage.py dbshell -- -c "
     SELECT 'zone' AS t, count(*) AS cells, sum(trip_count) AS trips FROM zones_ridesharezonehourstats
     UNION ALL
     SELECT 'route', count(*), sum(trip_count) FROM zones_rideshareroutehourstats;"
   ```

   (`dbshell` needs `psql` installed; otherwise run the same query in any PostgreSQL client.)

5. **Close the database again**: remove the rule you added, then end the shell session (or `unset DATABASE_URL`).

   ```bash
   aws ec2 revoke-security-group-ingress --region us-east-2 \
       --group-id "$SG" --protocol tcp --port 5432 --cidr "$MYIP/32"
   unset DATABASE_URL
   ```

If the import fails partway, the old rideshare rows stay in place (one transaction); fix the cause and run it again. Remove the IP rule even if the import failed.

## Staff accounts (the admin)

The Django admin at `/admin/` is for staff accounts only (US39 #113). Riders and guests get the admin sign-in page instead, and only staff see the "Admin" link in the site header. A staff account is a normal account (an email and a password) with the staff and superuser flags set. Staff sign in with their email, at `/admin/` or on the site's own sign-in page.

**Never write a staff member's email, username or password into the code, settings, migrations, fixtures, docs, an issue or a commit message.** The commands below ask for the password in the terminal and never take it as an option.

> **Do not sign in to the admin on Production (or Integration) until HTTPS is enabled.** Both AWS sites are plain `http://`, so a staff password and the admin session cookie would cross the internet unencrypted, and a staff account can change everything in the shared database. Until then, use the admin on your own laptop (`http://127.0.0.1:8000/admin/`). See `docs/decisions.md` (US39).

### Create a staff account

Locally (uses the database in `.env`):

```bash
python manage.py create_staff                 # asks for the email, then the password twice
python manage.py create_staff --email <email> # the same, without the email prompt
python manage.py create_staff --email <email> --existing   # make an existing account staff; its password is not changed
```

The password must pass the same rules as sign-up (at least 8 characters, not common, not all numbers, not like the email). The command stops without saving anything if the email already has an account (unless `--existing`), the two passwords differ, or the password is too weak. It refuses to run without a terminal, so a password can't be piped in from a file or a script.

Django's own `python manage.py createsuperuser` also works, but enter the email in lowercase as the **Username** (accounts use the lowercased email as the username), or the account can't sign in. Prefer `create_staff`.

**Integration and Production.** Recommended path: enable HTTPS on the AWS sites first, then create staff accounts there. Until HTTPS is on, staff can't safely sign in to the admin on AWS anyway (see the warning above).

**Not yet tested:** the two ways below have not been run against the AWS database. Check each step as you go and update this section once one has worked.

Both sites share one RDS database, so a staff account created once works on both. Create it from a laptop, the same way the rideshare data is loaded (see "Load the rideshare data into the shared AWS database" above):

1. Allow your IP on port 5432 in the `taxiscope-db-sg` security group (step 1 there).
2. Point Django at RDS in this shell only (step 2 there): `read -rs DATABASE_URL && export DATABASE_URL`.
3. Run `python manage.py create_staff`.
4. Remove your IP rule and `unset DATABASE_URL` (step 5 there).

Alternative (**not yet tested**): run the command on an Elastic Beanstalk instance. It needs the EB CLI and an EC2 key pair on the environment.

```bash
eb ssh Taxiscope-integration-env
sudo -s
cd /var/app/current
source /var/app/venv/*/bin/activate
export $(/opt/elasticbeanstalk/bin/get-config --output YAML environment | sed -r 's/: /=/' | xargs)
python manage.py create_staff
exit    # leave the root shell, then exit again to close the SSH session
```

### Remove a staff account

```bash
python manage.py remove_staff --email <email>
```

This takes away the staff rights at once (Django checks them on every admin page, so a staff member who is signed in loses access on their next click). The account itself is kept as a normal rider account. To delete it completely, a staff member deletes it in the admin (Accounts → the account → Delete), or its owner deletes it from My account. Deleting it deletes everything saved in it (US12). On Integration and Production (**not yet tested**), run `remove_staff` from a laptop with the same four steps as above (step 3 becomes `remove_staff`).

### What staff can do in the admin

- **Accounts:** list and search by email or display name, deactivate (untick "Active") or delete an account. The password and its hash are not shown and can't be reset there, the staff flags are read-only (they change only with the commands above), and accounts can't be added there (they come from sign-up or `create_staff`).
- **Zones:** read-only for now (US42 makes the names editable).
- Display names, fare reports, ride posts, interest in rides and content reports, as set up by their stories (US24, US30, US31, US33, US38).

## Development checks

CI (see `docs/ci.md`) runs these on every push. Install the extra tools once:

```bash
pip install -r requirements-dev.txt
```

Then, from the repo root:

```bash
black .                        # reformat; CI only checks (black --check .)
flake8                         # lint (config in .flake8)
coverage run manage.py test    # Django tests, instrumented for coverage
coverage report                # per-file and total coverage (config in .coveragerc)
node --test zones/tests/*.test.js   # JavaScript tests
```

## Regenerate the adjacent zones

`zones/data/zone_neighbors.json` (US18) lists, for every zone, the zones that share a border with it. It is committed, so you only need this after rebuilding `taxi_zones.geojson`. The script needs `shapely`, which the app does not use, so it is not in `requirements.txt`:

```bash
pip install shapely==2.1.2
python scripts/build_zone_neighbors.py
python manage.py test zones.tests.test_zone_neighbors
```

The rule (a shared border of at least 10 m; corners and rivers do not count) is in `docs/decisions.md` (adjacent zones).
