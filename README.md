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
