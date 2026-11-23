import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from zones.importer import history, rules
from zones.importer.download import parse_month, repeated_months
from zones.importer.read import TripFileError
from zones.importer.report import format_report
from zones.importer.rideshare.clean import rules as rideshare_rules
from zones.importer.rideshare.pipeline import run_rideshare_import
from zones.models import ImportRun


class Command(BaseCommand):
    help = (
        "Import monthly NYC TLC High Volume FHV (Uber and Lyft) trip files and "
        "replace the rideshare zone and route statistics with them. Missing "
        "files are downloaded. The taxi statistics are not touched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            action="append",
            dest="months",
            type=parse_month,
            required=True,
            metavar="YYYY-MM",
            help="A month to import. Repeat for more months.",
        )
        parser.add_argument(
            "--data-dir",
            type=Path,
            default=settings.BASE_DIR / "data" / "raw",
            help="Folder for the monthly Parquet files (default: data/raw).",
        )
        history.add_by_argument(parser)

    def handle(self, *args, months, data_dir, by=None, **options):
        repeated = repeated_months(months)
        if repeated:
            raise CommandError(
                f"Each month can be given only once: {', '.join(repeated)}"
            )

        started = time.monotonic()
        # US41: the limits in the admin now; a change during the run
        # applies from the next import.
        limits = rules.current_limits(ImportRun.Dataset.RIDESHARE)
        cleaning_rules = rideshare_rules(limits)
        run = history.start_run(
            ImportRun.Dataset.RIDESHARE, months, by or history.default_run_by(), limits
        )
        with history.failure_recorded(run, self.stderr):
            try:
                result = run_rideshare_import(
                    months, data_dir, progress=self.stdout.write, limits=limits
                )
            except TripFileError as exc:
                raise CommandError(str(exc)) from exc

        report = format_report(
            result.months, result.zone_stats, result.route_stats, cleaning_rules
        )
        history.record_success(run, result, cleaning_rules, report)
        self.stdout.write("")
        self.stdout.write(report)
        self.stdout.write("")
        self.stdout.write(
            f"Zones loaded: {result.zones_loaded}. "
            f"Finished in {time.monotonic() - started:.0f} s."
        )
