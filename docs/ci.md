# CI pipeline

Continuous integration runs on Travis CI (`app.travis-ci.com`), configured in
`.travis.yml`. Coverage results are uploaded to Coveralls. There is no deploy
step yet; this is tracked separately.

## What runs, in order

1. **Install:** `pip install -r requirements-dev.txt` (installs
   `requirements.txt` plus black, flake8, coverage, coveralls).
2. **`black --check .`** — fails the build if any file is not already
   formatted. Run `black .` locally and commit the result before pushing.
3. **`flake8`** — lint, configured in `.flake8` (max line length 88, `E203`
   ignored because black and flake8 disagree about whitespace before `:` in
   slices).
4. **`coverage run manage.py test`** — the full Django test suite
   (`zones/tests/`), instrumented for coverage per `.coveragerc`.
5. **`coverage report`** — prints the per-file and total percentage to the
   build log.
6. **`node --test zones/tests/*.test.js`** — the JavaScript unit tests for
   the frontend (`zones/static/zones/js/`), run with Node's built-in test
   runner, no extra install needed.
7. **`after_success`: `coveralls`** — uploads the coverage data gathered in
   step 4 to Coveralls, tagged with the Travis branch
   (`CI_BRANCH=$TRAVIS_BRANCH`) so develop and main report separately.

Any step failing stops the build. A build failure sends an email (see
`notifications` in `.travis.yml`); nothing posts on success.

## Database

The app only supports PostgreSQL (`taxiscope/settings.py` parses a single
`DATABASE_URL` and forces the `postgresql` engine). Travis's `jammy` image
bundles PostgreSQL 14; `.travis.yml` starts it with `services: postgresql`
and pins `addons.postgresql: "14"` (version 16 is not available on `jammy` —
it would need `dist: noble`, which this project does not use). The default
`postgres` user and port `5432` are used, matching Travis's documented
defaults for a preinstalled version.

Django's test runner creates and drops its own test database on each run
(via a `nodb` connection to the `postgres` maintenance database), so the
`DATABASE_URL` database does not need to exist beforehand for `manage.py
test` to work. `before_script` still creates it, matching Travis's
documented PostgreSQL setup, in case a future CI step connects to the
database directly (for example a migration check).

**Known risk:** community reports describe PostgreSQL occasionally failing
to start automatically on Travis's `jammy` image (a `postgresql.service`
not found error), with `group: previous` suggested as a workaround in one
thread. This was not reproducible locally (only Travis's own `jammy`
workers run that image), so if a build fails at the `services` step with a
PostgreSQL startup error, try adding `group: previous` to `.travis.yml` next
to `dist: jammy`.

## Secrets

`SECRET_KEY` and `DATABASE_URL` are set directly in `.travis.yml`'s
`env.global`, but they are CI-only dummy values with no access to anything
real (`DEBUG=True`, a throwaway `SECRET_KEY`, a database that only exists for
the build). No real credentials are stored in the repository. Coveralls'
upload token is not configured here — it is picked up automatically by the
`coveralls` CLI from Travis's own environment variables
(`TRAVIS`, `TRAVIS_JOB_ID`) when the build runs on `app.travis-ci.com` with
the repository enabled in Coveralls.

## Manual setup required (not in this repository)

- **Travis CI:** enable the repository at app.travis-ci.com (Settings →
  GitHub Apps / repository list). No extra environment variables need to be
  set there; everything CI needs is in `.travis.yml`.
- **Coveralls:** enable the repository at coveralls.io so it accepts the
  upload the build sends. Coveralls' standard Travis integration reads the
  build identity Travis already provides, so no extra token needs to be
  pasted into Travis's settings.
- **Branch protection (optional, not done here):** requiring the Travis
  check to pass before merging into `develop`/`main` is a GitHub branch
  protection setting, not a file in this repository.

## Running the same checks locally

See the README's "Development checks" section.
