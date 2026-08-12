from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

YEAR = r"(?:19|20)\d{2}"
DATE_RE = re.compile(
    rf"(?P<year>{YEAR})[年\-/\.](?P<month>0?[1-9]|1[0-2])[月\-/\.]"
    r"(?P<day>0?[1-9]|[12]\d|3[01])日?"
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
        year, month, day = (
            int(date_match.group("year")),
            int(date_match.group("month")),
            int(date_match.group("day")),
        )
        _, max_day = calendar.monthrange(year, month)
        if day <= max_day:
            start = datetime(year, month, day, tzinfo=tz)
            end = _date_at_end(year, month, day, tz)
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
