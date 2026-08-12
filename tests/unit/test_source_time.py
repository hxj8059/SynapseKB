from datetime import datetime
from zoneinfo import ZoneInfo

from synapsekb.temporal.source_time import extract_source_time

TZ = ZoneInfo("Asia/Shanghai")


def test_explicit_source_time_has_highest_priority() -> None:
    explicit = datetime(2024, 2, 3, tzinfo=TZ)
    result = extract_source_time(
        explicit=explicit,
        filename="报告-2025-01-02.pdf",
        content="发布日期 2026-03-04",
    )
    assert result == explicit


def test_filename_date_is_extracted() -> None:
    result = extract_source_time(filename="经营分析_2024-08-31.pdf")
    assert result == datetime(2024, 8, 31, tzinfo=TZ)


def test_ambiguous_content_keeps_source_time_unknown() -> None:
    result = extract_source_time(content="2024-01-01 旧版；2025-01-01 新版。")
    assert result is None


def test_upload_time_is_never_used_as_source_time() -> None:
    assert extract_source_time(filename="没有日期的文档.pdf", content="无可靠日期") is None
