# team5-mon-fall26

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

## Import the trip data

```bash
python manage.py import_trips --month 2026-03 --month 2026-04 --month 2026-05
```

Downloads any missing monthly file into `data/raw/` (about 65 MB each, gitignored), then replaces all statistics in one transaction. Re-running is safe. Running it with fewer months replaces the statistics with just those months. At the end it prints a report: rows read, removed per cleaning rule, and kept, for each month and in total.

For the three months above it takes about 1.5 minutes and up to about 1.2 GB of memory (measured on a laptop against a local PostgreSQL).
