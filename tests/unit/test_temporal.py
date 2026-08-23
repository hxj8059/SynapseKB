from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from synapsekb.api.schemas import TimeFilter
from synapsekb.temporal.parser import resolve_time_ranges

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=TZ)


def test_last_year_is_a_strict_source_time_range() -> None:
    ranges = resolve_time_ranges("只看去年发布的报告", now=NOW)
    assert len(ranges) == 1
    resolved = ranges[0]
    assert resolved.field == "source_time"
    assert resolved.include_unknown is False
    assert resolved.from_time == datetime(2025, 1, 1, tzinfo=TZ)
    assert resolved.to_time == datetime(2025, 12, 31, 23, 59, 59, 999999, tzinfo=TZ)


def test_comparison_produces_independent_ranges() -> None:
    ranges = resolve_time_ranges("比较 2023 年和 2025 年的政策", now=NOW)
    assert [item.from_time.year for item in ranges if item.from_time] == [2023, 2025]
    assert all(item.include_unknown is False for item in ranges)


def test_recent_three_months_uses_user_timezone() -> None:
    resolved = resolve_time_ranges("最近三个月有哪些变化", now=NOW)[0]
    assert resolved.from_time == datetime(2026, 4, 30, 12, 0, tzinfo=TZ)
    assert resolved.to_time == NOW


def test_no_time_expression_returns_no_filter() -> None:
    assert resolve_time_ranges("介绍这份文档", now=NOW) == []


def test_two_digit_month_and_day_are_not_truncated() -> None:
    resolved = resolve_time_ranges("只看 2026-12-31 的报告", now=NOW)[0]
    assert resolved.label == "2026-12-31"
    assert resolved.from_time == datetime(2026, 12, 31, tzinfo=TZ)
    assert resolved.to_time == datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=TZ)


def test_explicit_timestamp_range_preserves_both_bounds_and_offset() -> None:
    query = (
        "分析 PCB 上游行业在 2026-06-21 00:00:00+08:00 "
        "至 2026-08-21 23:59:59.999999+08:00 的每周变化"
    )
    resolved = resolve_time_ranges(query, now=NOW)[0]
    assert resolved.label == (
        "2026-06-21 00:00:00+08:00 至 2026-08-21 23:59:59.999999+08:00"
    )
    assert resolved.from_time == datetime(2026, 6, 21, tzinfo=TZ)
    assert resolved.to_time == datetime(2026, 8, 21, 23, 59, 59, 999999, tzinfo=TZ)
    assert resolved.from_time.utcoffset() == TZ.utcoffset(resolved.from_time)
    assert resolved.to_time.utcoffset() == TZ.utcoffset(resolved.to_time)


def test_date_only_range_includes_the_complete_last_day() -> None:
    resolved = resolve_time_ranges("查看 2026年6月21日 到 2026年8月21日", now=NOW)[0]
    assert resolved.from_time == datetime(2026, 6, 21, tzinfo=TZ)
    assert resolved.to_time == datetime(2026, 8, 21, 23, 59, 59, 999999, tzinfo=TZ)


def test_invalid_calendar_date_is_not_partially_matched() -> None:
    assert resolve_time_ranges("查看 2026-06-32 的报告", now=NOW) == []


def test_structured_time_filter_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        TimeFilter.model_validate(
            {
                "field": "source_time",
                "from": "2024-01-01T00:00:00",
                "to": "2024-12-31T23:59:59",
            }
        )
