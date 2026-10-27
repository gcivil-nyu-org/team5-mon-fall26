"""The import report: rows read, removed per rule and kept, then cells."""

from dataclasses import dataclass

from zones.importer.clean import RULES

# Only for the report. The import stores every cell; the API applies the
# minimum trip count (see docs/decisions.md).
REPORT_MIN_TRIPS = 5

LABEL_WIDTH = 36
NUMBER_WIDTH = 12


@dataclass
class MonthReport:
    month: str
    rows_read: int
    removed: dict
    rows_kept: int

    @property
    def rows_removed(self):
        return sum(self.removed.values())


def total_report(months):
    return MonthReport(
        month="Total",
        rows_read=sum(m.rows_read for m in months),
        removed={key: sum(m.removed[key] for m in months) for key, _ in RULES},
        rows_kept=sum(m.rows_kept for m in months),
    )


def _line(label, number, note=""):
    text = f"  {label:<{LABEL_WIDTH}}{number:>{NUMBER_WIDTH},}"
    return f"{text}  ({note})" if note else text


def _block(title, report):
    share = report.rows_removed / report.rows_read if report.rows_read else 0
    lines = [title, _line("Rows read", report.rows_read)]
    lines += [_line(label, report.removed[key]) for key, label in RULES]
    lines.append(_line("Rows removed", report.rows_removed, f"{share:.2%}"))
    lines.append(_line("Rows kept", report.rows_kept))
    return "\n".join(lines)


def _cells_line(label, stats):
    small = int((stats["trip_count"] < REPORT_MIN_TRIPS).sum())
    return f"{label:<{LABEL_WIDTH + 2}}{len(stats):>{NUMBER_WIDTH},}  ({small:,} with fewer than {REPORT_MIN_TRIPS} trips)"


def format_report(months, zone_stats, route_stats):
    blocks = [f"Months loaded: {', '.join(m.month for m in months)}"]
    blocks += [_block(m.month, m) for m in months]
    plural = "month" if len(months) == 1 else "months"
    blocks.append(_block(f"Total ({len(months)} {plural})", total_report(months)))
    blocks.append(
        "\n".join(
            [
                _cells_line("Zone cells", zone_stats),
                _cells_line("Route cells", route_stats),
            ]
        )
    )
    return "\n\n".join(blocks)
