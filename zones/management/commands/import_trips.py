import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from zones.importer.download import parse_month
from zones.importer.pipeline import run_import
from zones.importer.read import TripFileError
from zones.importer.report import format_report


class Command(BaseCommand):
    help = (
        "Import monthly NYC TLC yellow taxi trip files and replace the zone "
        "and route statistics with them. Missing files are downloaded."
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

    def handle(self, *args, months, data_dir, **options):
        repeated = sorted({month for month in months if months.count(month) > 1})
        if repeated:
            raise CommandError(f"Each month can be given only once: {', '.join(repeated)}")

        started = time.monotonic()
        try:
            result = run_import(months, data_dir, progress=self.stdout.write)
        except TripFileError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("")
        self.stdout.write(format_report(result.months, result.zone_stats, result.route_stats))
        self.stdout.write("")
        self.stdout.write(
            f"Zones loaded: {result.zones_loaded}. "
            f"Finished in {time.monotonic() - started:.0f} s."
        )
