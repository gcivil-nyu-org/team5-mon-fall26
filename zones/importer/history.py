"""The import history (US40 #114): one ImportRun per run of import_trips or
import_rideshare, written to the database the command runs against.

The record is saved as "running" before the import starts, in autocommit,
outside the import's own transaction (load_all / load_rideshare). So when
the import fails and its transaction rolls back, the record is still
there to be marked "failed". A process that is killed or runs out of
memory leaves its record "running"; the next run of the same import
closes it as failed (see STALE_ERROR and docs/decisions.md, US40).
"""

import argparse
import getpass
from contextlib import contextmanager

from django.conf import settings
from django.core.management import CommandError
from django.db import connection
from django.utils import timezone

from zones.importer import clean as taxi_clean
from zones.importer import rules
from zones.importer.report import small_cells, total_report
from zones.importer.rideshare.read import LYFT, UBER
from zones.models import ImportRun

UNKNOWN_USER = "unknown"
RUN_BY_MAX = ImportRun._meta.get_field("run_by").max_length
INTERRUPTED = "Interrupted (Ctrl-C) before it finished."
STALE_ERROR = (
    "Did not finish: the import stopped without saving a result (for "
    "example it was killed, ran out of memory, or lost the database "
    "connection). Closed by run {run_id}, started {started:%Y-%m-%d %H:%M} UTC."
)


def cleaning_limits(dataset, limits):
    """The cleaning limits the run uses, by name: the editable ones it read
    from the admin (US41, zones/importer/rules.py) and the fixed ones in
    the code."""
    saved = rules.saved_limits(limits)
    saved["UNKNOWN_ZONE_IDS"] = sorted(taxi_clean.UNKNOWN_ZONE_IDS)
    if dataset == ImportRun.Dataset.TAXI:
        saved["VOIDED_PAYMENT_TYPE"] = taxi_clean.VOIDED_PAYMENT_TYPE
    else:
        saved["PROVIDERS"] = [UBER, LYFT]
    return saved


def run_by_argument(value):
    """argparse type for --by: trimmed, not blank, at most RUN_BY_MAX."""
    value = value.strip()
    if not value or len(value) > RUN_BY_MAX:
        raise argparse.ArgumentTypeError(f"give a name of 1 to {RUN_BY_MAX} characters")
    return value


def add_by_argument(parser):
    parser.add_argument(
        "--by",
        type=run_by_argument,
        metavar="NAME",
        help=(
            "Who is running the import, saved in the import history "
            "(default: your operating-system user name)."
        ),
    )


def default_run_by():
    try:
        return getpass.getuser() or UNKNOWN_USER
    except Exception:  # no user name in the environment or the system
        return UNKNOWN_USER


def _release_connection():
    """Close the connection outside a transaction, so the next query opens
    a fresh one. Before the long read-and-clean part this keeps the import
    from holding an idle connection (it opened none there before US40);
    after a failure it replaces a connection that may have been lost."""
    if not connection.in_atomic_block:
        connection.close()


def error_message(exc):
    if isinstance(exc, KeyboardInterrupt):
        return INTERRUPTED
    message = str(exc)
    if isinstance(exc, CommandError):
        return message
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


def start_run(dataset, months, run_by, limits):
    """Save a "running" record with the limits the run uses, and close any
    earlier run of the same import that never finished."""
    run = ImportRun.objects.create(
        dataset=dataset,
        months=list(months),
        run_by=run_by,
        started_at=timezone.now(),
        min_trip_count=settings.MIN_TRIP_COUNT,
        cleaning_limits=cleaning_limits(dataset, limits),
    )
    ImportRun.objects.filter(dataset=dataset, status=ImportRun.Status.RUNNING).exclude(
        pk=run.pk
    ).update(
        status=ImportRun.Status.FAILED,
        error=STALE_ERROR.format(run_id=run.pk, started=run.started_at),
    )
    _release_connection()
    return run


def record_success(run, result, rules, report):
    """Fill the record from the result and report the command prints."""
    total = total_report(result.months, rules)
    run.status = ImportRun.Status.SUCCEEDED
    run.finished_at = timezone.now()
    run.rows_read = total.rows_read
    run.removed_by_rule = total.removed
    run.rows_removed = total.rows_removed
    run.rows_kept = total.rows_kept
    run.waits_left_out = total.waits_left_out
    run.zone_cells = len(result.zone_stats)
    run.route_cells = len(result.route_stats)
    run.small_zone_cells = small_cells(result.zone_stats)
    run.small_route_cells = small_cells(result.route_stats)
    run.zones_loaded = result.zones_loaded
    run.report = report
    run.error = ""
    run.save()


def record_failure(run, exc):
    _release_connection()
    run.status = ImportRun.Status.FAILED
    run.finished_at = timezone.now()
    run.error = error_message(exc)
    run.save()


@contextmanager
def failure_recorded(run, stderr):
    """Mark the run failed if the block raises anything (Ctrl-C too), then
    raise it again unchanged. If even that save fails, say so on stderr
    and still raise the import's own error."""
    try:
        yield
    except BaseException as exc:
        try:
            record_failure(run, exc)
        except Exception as save_error:
            stderr.write(
                f"Could not save the failed run to the import history: {save_error}"
            )
        raise
