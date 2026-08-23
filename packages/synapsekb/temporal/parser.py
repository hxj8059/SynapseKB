from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from datetime import timezone as fixed_timezone
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

YEAR = r"(?:19|20)\d{2}"
MONTH = r"(?:1[0-2]|0?[1-9])"
DAY = r"(?:3[01]|[12]\d|0?[1-9])"


def _timestamp_pattern(prefix: str) -> str:
    return (
        rf"(?<!\d)(?P<{prefix}year>{YEAR})[年\-/\.]"
        rf"(?P<{prefix}month>{MONTH})[月\-/\.]"
        rf"(?P<{prefix}day>{DAY})日?(?!\d)"
        rf"(?:[T\s]+(?P<{prefix}hour>[01]\d|2[0-3])"
        rf":(?P<{prefix}minute>[0-5]\d)"
        rf"(?::(?P<{prefix}second>[0-5]\d)"
        rf"(?:\.(?P<{prefix}fraction>\d{{1,9}}))?)?"
        rf"(?P<{prefix}offset>Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)?)?"
    )


DATE_RE = re.compile(_timestamp_pattern(""), re.IGNORECASE)
DATE_RANGE_RE = re.compile(
    _timestamp_pattern("start_")
    + r"(?:\s*(?:到|至|～|~|—|–|to)\s*|\s+-\s+)"
    + _timestamp_pattern("end_"),
    re.IGNORECASE,
)
YEAR_RANGE_RE = re.compile(
    rf"(?P<start>{YEAR})\s*年?\s*(?:到|至|～|~|—|–|-)\s*(?P<end>{YEAR})\s*年?"
)
YEAR_RE = re.compile(rf"(?P<year>{YEAR})\s*年")


@dataclass(frozen=True, slots=True)
class ResolvedTimeRange:
    label: str
    from_time: datetime | None
    to_time: datetime | None
    field: str = "source_time"
    include_unknown: bool = False

    def summary(self) -> str:
        start = self.from_time.isoformat() if self.from_time else "不限"
        end = self.to_time.isoformat() if self.to_time else "不限"
        return f"已将“{self.label}”解析为 {start} 至 {end}，检索字段为 {self.field}。"


def _year_range(year: int, tz: ZoneInfo, label: str) -> ResolvedTimeRange:
    start = datetime(year, 1, 1, tzinfo=tz)
    end = datetime(year + 1, 1, 1, tzinfo=tz) - timedelta(microseconds=1)
    return ResolvedTimeRange(label=label, from_time=start, to_time=end)


def _date_at_end(year: int, month: int, day: int, tz: ZoneInfo) -> datetime:
    return datetime(year, month, day, 23, 59, 59, 999999, tzinfo=tz)


def _offset_timezone(raw: str | None, fallback: tzinfo) -> tzinfo:
    if not raw:
        return fallback
    if raw.casefold() == "z":
        return UTC
    compact = raw.replace(":", "")
    sign = 1 if compact[0] == "+" else -1
    delta = timedelta(hours=int(compact[1:3]), minutes=int(compact[3:5]))
    return fixed_timezone(sign * delta)


def _timestamp_from_match(
    match: re.Match[str],
    *,
    prefix: str,
    fallback_timezone: tzinfo,
    end_of_day_when_date_only: bool,
) -> tuple[datetime, bool] | None:
    year = int(match.group(f"{prefix}year"))
    month = int(match.group(f"{prefix}month"))
    day = int(match.group(f"{prefix}day"))
    hour_group = match.group(f"{prefix}hour")
    has_time = hour_group is not None
    if has_time:
        hour = int(hour_group)
        minute = int(match.group(f"{prefix}minute"))
        second_group = match.group(f"{prefix}second")
        second = int(second_group) if second_group else 0
        fraction = match.group(f"{prefix}fraction") or ""
        microsecond = int(fraction[:6].ljust(6, "0")) if fraction else 0
    elif end_of_day_when_date_only:
        hour, minute, second, microsecond = 23, 59, 59, 999999
    else:
        hour, minute, second, microsecond = 0, 0, 0, 0
    timezone_value = _offset_timezone(
        match.group(f"{prefix}offset"),
        fallback_timezone,
    )
    try:
        return (
            datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                microsecond,
                tzinfo=timezone_value,
            ),
            has_time,
        )
    except ValueError:
        return None


def _last_quarter(now: datetime, tz: ZoneInfo) -> ResolvedTimeRange:
    current_quarter_start_month = ((now.month - 1) // 3) * 3 + 1
    current_quarter_start = datetime(now.year, current_quarter_start_month, 1, tzinfo=tz)
    start = current_quarter_start - relativedelta(months=3)
    end = current_quarter_start - timedelta(microseconds=1)
    return ResolvedTimeRange("上季度", start, end)


def resolve_time_ranges(
    text: str,
    *,
    now: datetime | None = None,
    timezone: str = "Asia/Shanghai",
) -> list[ResolvedTimeRange]:
    """Resolve explicit/relative Chinese time expressions.

    Multiple ranges are returned for comparison questions so callers must run
    independent retrievals instead of widening them into one range.
    """

    tz = ZoneInfo(timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)

    comparison_years = [int(item) for item in YEAR_RE.findall(text)]
    if ("比较" in text or "对比" in text) and len(set(comparison_years)) >= 2:
        return [_year_range(year, tz, f"{year}年") for year in dict.fromkeys(comparison_years)]

    date_range_match = DATE_RANGE_RE.search(text)
    if date_range_match:
        parsed_start = _timestamp_from_match(
            date_range_match,
            prefix="start_",
            fallback_timezone=tz,
            end_of_day_when_date_only=False,
        )
        parsed_end = _timestamp_from_match(
            date_range_match,
            prefix="end_",
            fallback_timezone=tz,
            end_of_day_when_date_only=True,
        )
        if parsed_start is not None and parsed_end is not None:
            start, start_has_time = parsed_start
            end, end_has_time = parsed_end
            if end < start:
                start, end = end, start
                start_has_time, end_has_time = end_has_time, start_has_time
                if not start_has_time:
                    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
                if not end_has_time:
                    end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
            return [
                ResolvedTimeRange(
                    label=date_range_match.group(0),
                    from_time=start,
                    to_time=end,
                )
            ]

    range_match = YEAR_RANGE_RE.search(text)
    if range_match:
        start_year = int(range_match.group("start"))
        end_year = int(range_match.group("end"))
        if end_year < start_year:
            start_year, end_year = end_year, start_year
        return [
            ResolvedTimeRange(
                label=range_match.group(0),
                from_time=datetime(start_year, 1, 1, tzinfo=tz),
                to_time=datetime(end_year + 1, 1, 1, tzinfo=tz) - timedelta(microseconds=1),
            )
        ]

    if "去年" in text:
        return [_year_range(current.year - 1, tz, "去年")]
    if "今年" in text:
        return [
            ResolvedTimeRange(
                "今年",
                datetime(current.year, 1, 1, tzinfo=tz),
                current,
            )
        ]
    if "上季度" in text:
        return [_last_quarter(current, tz)]

    recent_months = re.search(r"最近\s*([一二两三四五六七八九十\d]+)\s*个?月", text)
    if recent_months:
        chinese_numbers = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        raw = recent_months.group(1)
        months = int(raw) if raw.isdigit() else chinese_numbers.get(raw)
        if months:
            return [
                ResolvedTimeRange(
                    recent_months.group(0),
                    current - relativedelta(months=months),
                    current,
                )
            ]

    date_match = DATE_RE.search(text)
    if date_match:
        parsed_date = _timestamp_from_match(
            date_match,
            prefix="",
            fallback_timezone=tz,
            end_of_day_when_date_only=False,
        )
        if parsed_date is not None:
            start, has_time = parsed_date
            end = (
                start
                if has_time
                else _date_at_end(start.year, start.month, start.day, tz)
            )
            if "截至" in text or "以前" in text or "之前" in text:
                return [ResolvedTimeRange(date_match.group(0), None, end)]
            if "以后" in text or "之后" in text:
                return [ResolvedTimeRange(date_match.group(0), start, None)]
            return [ResolvedTimeRange(date_match.group(0), start, end)]

    year_match = YEAR_RE.search(text)
    if year_match:
        year = int(year_match.group("year"))
        if "以前" in text or "之前" in text or "截至" in text:
            return [
                ResolvedTimeRange(
                    year_match.group(0),
                    None,
                    datetime(year + 1, 1, 1, tzinfo=tz) - timedelta(microseconds=1),
                )
            ]
        if "以后" in text or "之后" in text:
            return [
                ResolvedTimeRange(
                    year_match.group(0),
                    datetime(year, 1, 1, tzinfo=tz),
                    None,
                )
            ]
        return [_year_range(year, tz, year_match.group(0))]
    return []
