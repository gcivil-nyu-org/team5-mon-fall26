"""US21 #50: iCalendar (.ics) files, written with the standard library.

Generic on purpose (a list of events in, .ics text out) so other plans can
reuse it. Every time is a New York wall-clock time, written with
TZID=America/New_York and the matching VTIMEZONE (RFC 5545).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NYC_TZID = "America/New_York"
NYC_TZ = ZoneInfo(NYC_TZID)
PRODID = "-//TaxiScope NYC//Trip plans//EN"

# US daylight-saving rules since 2007: EDT from the 2nd Sunday of March,
# EST from the 1st Sunday of November, both at 02:00 local time.
VTIMEZONE_NYC = [
    "BEGIN:VTIMEZONE",
    f"TZID:{NYC_TZID}",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:-0500",
    "TZOFFSETTO:-0400",
    "TZNAME:EDT",
    "DTSTART:20070311T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:-0400",
    "TZOFFSETTO:-0500",
    "TZNAME:EST",
    "DTSTART:20071104T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
]

LINE_OCTETS = 75


@dataclass(frozen=True)
class CalendarEvent:
    uid: str
    start: datetime  # aware, New York
    end: datetime  # equal to start for a point in time
    summary: str
    description: str
    alarm_minutes: int = 15
    weekly: bool = False


def next_occurrence(day_of_week, hour, minute, now):
    """The next New York datetime on day_of_week (Monday=0) at hour:minute
    that is not before now. Today counts if the time has not passed.

    A time that happens twice when clocks go back is the first one (EDT).
    Compared in UTC, so that hour is handled correctly too.
    """
    now = now.astimezone(NYC_TZ)
    date = now.date() + timedelta(days=(day_of_week - now.weekday()) % 7)
    start = datetime(date.year, date.month, date.day, hour, minute, tzinfo=NYC_TZ)
    if start.astimezone(timezone.utc) < now.astimezone(timezone.utc):
        date += timedelta(days=7)
        start = datetime(date.year, date.month, date.day, hour, minute, tzinfo=NYC_TZ)
    return start


def escape_text(value):
    """Escape a TEXT value: backslash, semicolon, comma and newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold_line(line):
    """Fold a content line at 75 octets, never inside a UTF-8 character.

    Continuation lines start with a space, which counts toward their 75.
    """
    parts = []
    current = ""
    octets = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if octets + size > LINE_OCTETS:
            parts.append(current)
            current, octets = " ", 1
        current += char
        octets += size
    parts.append(current)
    return "\r\n".join(parts)


def _local(value):
    return value.astimezone(NYC_TZ).strftime("%Y%m%dT%H%M%S")


def _trigger(minutes):
    return f"-PT{minutes // 60}H" if minutes % 60 == 0 else f"-PT{minutes}M"


def build_ics(events, now):
    """The .ics text (CRLF line endings) for events; DTSTAMP is now in UTC."""
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *VTIMEZONE_NYC,
    ]
    for event in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID={NYC_TZID}:{_local(event.start)}",
            f"DTEND;TZID={NYC_TZID}:{_local(event.end)}",
        ]
        if event.weekly:
            lines.append("RRULE:FREQ=WEEKLY")
        lines += [
            f"SUMMARY:{escape_text(event.summary)}",
            f"DESCRIPTION:{escape_text(event.description)}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{escape_text(event.summary)}",
            f"TRIGGER:{_trigger(event.alarm_minutes)}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(f"{fold_line(line)}\r\n" for line in lines)
