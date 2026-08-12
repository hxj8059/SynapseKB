from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>19\d{2}|20\d{2})"
    r"(?:[年._\-/])(?P<month>0?[1-9]|1[0-2])"
    r"(?:[月._\-/])(?P<day>0?[1-9]|[12]\d|3[01])日?(?!\d)"
)


def parse_explicit_date(value: str, timezone: str = "Asia/Shanghai") -> datetime | None:
    match = DATE_PATTERN.search(value)
    if not match:
        return None
    try:
        return datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            tzinfo=ZoneInfo(timezone),
        )
    except ValueError:
        return None


def extract_source_time(
    *,
    explicit: datetime | None = None,
    file_metadata_time: datetime | None = None,
    filename: str | None = None,
    content: str | None = None,
    timezone: str = "Asia/Shanghai",
) -> datetime | None:
    """Apply the product's strict source-time priority.

    Content is accepted only when one full date is clearly dominant. A bare year,
    ambiguous collection of dates, or missing evidence yields None.
    """

    if explicit is not None:
        return explicit
    if file_metadata_time is not None:
        return file_metadata_time
    if filename:
        parsed = parse_explicit_date(Path(filename).stem, timezone)
        if parsed is not None:
            return parsed
    if not content:
        return None
    matches = [match.group(0) for match in DATE_PATTERN.finditer(content[:50_000])]
    if not matches:
        return None
    counts = Counter(matches)
    best, count = counts.most_common(1)[0]
    if len(counts) > 1 and count == counts.most_common(2)[1][1]:
        return None
    return parse_explicit_date(best, timezone)
