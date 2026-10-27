# CI pipeline

Continuous integration runs on Travis CI (`app.travis-ci.com`), configured in
`.travis.yml`. Coverage results are uploaded to Coveralls. Continuous
deployment to AWS Elastic Beanstalk runs from the same file; see
[Continuous deployment](#continuous-deployment) below.

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
   `COVERALLS_SERVICE_NAME=travis-pro` is also set: on the first real build,
   the upload arrived in Coveralls with a blank branch under the default
   `travis-ci` service name (this project builds on `app.travis-ci.com`,
   Travis's `.com`/Pro side, not the legacy `.org` service that
   `travis-ci` assumes). Setting the service name to `travis-pro` fixed the
   branch tagging.

8. **`deploy`** — only on pushes to `develop` or `main`; see
   [Continuous deployment](#continuous-deployment).

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

The deploy step's AWS credentials are `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`, stored as hidden environment variables in the Travis
repository settings. dpl reads them from the environment. They must never be
written into `.travis.yml` or any other file in the repository.

## Manual setup required (not in this repository)

- **Travis CI:** enable the repository at app.travis-ci.com (Settings →
  GitHub Apps / repository list). No extra environment variables need to be
  set there for CI; everything CI needs is in `.travis.yml`. For deploys,
  `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are set there as hidden
  variables (done).
- **Coveralls:** enable the repository at coveralls.io so it accepts the
  upload the build sends. Coveralls' standard Travis integration reads the
  build identity Travis already provides, so no extra token needs to be
  pasted into Travis's settings.
- **Branch protection (optional, not done here):** requiring the Travis
  check to pass before merging into `develop`/`main` is a GitHub branch
  protection setting, not a file in this repository.

## Continuous deployment

Travis deploys with dpl v2 (`edge: true`), provider `elasticbeanstalk`, to the
Elastic Beanstalk application `taxiscope` in `us-east-2`. Both environments run
Python 3.14 on Amazon Linux 2023. dpl zips the build directory (skipping what
`.gitignore` matches), uploads it to the
`elasticbeanstalk-us-east-2-933164653260` bucket, creates an application
version labelled `travis-<sha>-<timestamp>`, and updates the environment.
`wait_until_deployed: true` makes the Travis build wait for the environment
update and fail if it fails.

| Push to | Deploys to | Instance |
|---|---|---|
| `develop` | `Taxiscope-integration-env` (capital T) | Integration |
| `main` | `taxiscope-env` | Production |

The deploy runs only if every earlier step passed. Pull request builds never
deploy (dpl skips the deploy step for them), and other branches do not match
`on: branch`.

**Cron builds are skipped.** Each target's `on:` has
`condition: "$TRAVIS_EVENT_TYPE != cron"` next to `branch`, and dpl needs both
to be true. A scheduled Travis cron build on `develop` or `main` still runs the
tests but does not redeploy.

**What runs on the instance.** The repository carries the same deploy files as
the bundle production was first deployed with (`eb deploy --staged` from
`c84c5d2`):

- `Procfile` — `gunicorn` on `127.0.0.1:8000`, 1 worker, 15 threads.
  `gunicorn` is pinned in `requirements.txt`.
- `.ebextensions/01_static.config` — the Elastic Beanstalk proxy serves
  `/static` from `staticfiles/`, which is `STATIC_ROOT` in
  `taxiscope/settings.py`. No whitenoise is needed.
- `.ebextensions/02_django.config` — `container_commands`: `migrate`
  (`leader_only: true`, so it runs once per deploy, not on every instance),
  then `collectstatic`. Both activate the platform venv first.

**Why `container_commands` instead of `.platform/hooks`.** The original bundle
ran migrate and collectstatic from `.platform/hooks/predeploy/*.sh`. Elastic
Beanstalk runs those hooks only if the files are executable. Travis builds its
own zip, and the executable bit may not survive the zip, so the hooks could be
skipped silently. `container_commands` are YAML and need no file permissions.

**Environment settings (not in the repository).** `SECRET_KEY`, `DEBUG`,
`ALLOWED_HOSTS` and `DATABASE_URL` are environment properties on each Elastic
Beanstalk environment. **Database access:** the database's security group must
allow inbound PostgreSQL (port 5432) from **each** environment's instance
security group, integration and production. If it does not, the deploy fails
at `01_migrate` because the instance cannot reach the database.

**Rule: nobody merges into `main` unless the latest deploy of `develop` to
Integration succeeded.** Check the Travis build for the `develop` merge commit
and the integration environment's health before opening or merging a
`develop` → `main` pull request.

## Running the same checks locally

See the README's "Development checks" section.
