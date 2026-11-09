"""The import report: rows read, removed per rule and kept, then cells.

Shared by the taxi and the rideshare imports: each passes its own rules.
"""

from dataclasses import dataclass

from django.conf import settings

from zones.importer.clean import RULES

# Only for the report. The import stores every cell; the API applies the
# minimum trip count (see docs/decisions.md).
REPORT_MIN_TRIPS = settings.MIN_TRIP_COUNT

LABEL_WIDTH = 36
NUMBER_WIDTH = 12
WAITS_LABEL = "Waits left out of the average"


@dataclass
class MonthReport:
    month: str
    rows_read: int
    removed: dict
    rows_kept: int
    # Rideshare only: kept trips whose wait is not in the wait average.
    # None for the taxi import, which has no wait.
    waits_left_out: int | None = None

    @property
    def rows_removed(self):
        return sum(self.removed.values())


def total_report(months, rules=RULES):
    waits = [m.waits_left_out for m in months]
    return MonthReport(
        month="Total",
        rows_read=sum(m.rows_read for m in months),
        removed={key: sum(m.removed[key] for m in months) for key, _ in rules},
        rows_kept=sum(m.rows_kept for m in months),
        waits_left_out=None if None in waits else sum(waits),
    )


def _share(part, whole):
    return f"{part / whole if whole else 0:.2%}"


def _block(title, report, rules, width):
    def line(label, number, note=""):
        text = f"  {label:<{width}}{number:>{NUMBER_WIDTH},}"
        return f"{text}  ({note})" if note else text

    lines = [title, line("Rows read", report.rows_read)]
    lines += [line(label, report.removed[key]) for key, label in rules]
    lines.append(
        line(
            "Rows removed",
            report.rows_removed,
            _share(report.rows_removed, report.rows_read),
        )
    )
    lines.append(line("Rows kept", report.rows_kept))
    if report.waits_left_out is not None:
        note = f"{_share(report.waits_left_out, report.rows_kept)} of kept"
        lines.append(line(WAITS_LABEL, report.waits_left_out, note))
    return "\n".join(lines)


def _cells_line(label, stats, width):
    small = int((stats["trip_count"] < REPORT_MIN_TRIPS).sum())
    count = f"{len(stats):>{NUMBER_WIDTH},}"
    note = f"({small:,} with fewer than {REPORT_MIN_TRIPS} trips)"
    return f"{label:<{width + 2}}{count}  {note}"


def format_report(months, zone_stats, route_stats, rules=RULES):
    # Wide enough for the longest label, so the numbers line up.
    width = max(LABEL_WIDTH, *(len(label) + 2 for _, label in rules))
    blocks = [f"Months loaded: {', '.join(m.month for m in months)}"]
    blocks += [_block(m.month, m, rules, width) for m in months]
    plural = "month" if len(months) == 1 else "months"
    blocks.append(
        _block(
            f"Total ({len(months)} {plural})", total_report(months, rules), rules, width
        )
    )
    blocks.append(
        "\n".join(
            [
                _cells_line("Zone cells", zone_stats, width),
                _cells_line("Route cells", route_stats, width),
            ]
        )
    )
    return "\n\n".join(blocks)
