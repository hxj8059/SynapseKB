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


def test_compact_filename_date_is_extracted() -> None:
    result = extract_source_time(filename="计算机行业周报_再谈Q3科技_20260725.pdf")
    assert result == datetime(2026, 7, 25, tzinfo=TZ)


def test_title_date_is_used_before_body_dates() -> None:
    result = extract_source_time(
        filename="研究报告.pdf",
        title="2026-07-03 NOVO Nordisk Weekly GLP-1 prescription trends",
        content="历史数据：2025-01-01、2024-01-01。",
    )
    assert result == datetime(2026, 7, 3, tzinfo=TZ)


def test_spaced_chinese_title_date_is_extracted() -> None:
    result = extract_source_time(title="行业周报 2026 年 7 月 25 日")
    assert result == datetime(2026, 7, 25, tzinfo=TZ)


def test_labelled_leading_date_beats_repeated_historical_dates() -> None:
    result = extract_source_time(
        content=(
            "证券研究报告\n发布日期：2026年7月25日\n"
            "历史比较 2025-01-01，基期 2025-01-01，去年同期 2025-01-01。"
        )
    )
    assert result == datetime(2026, 7, 25, tzinfo=TZ)


def test_single_cover_date_is_extracted_when_later_dates_differ() -> None:
    result = extract_source_time(
        content=(
            "计算机行业周报\n2026-07-25\n核心观点\n"
            + "正文" * 500
            + "\n历史数据 2025-01-01 与 2024-01-01"
        )
    )
    assert result == datetime(2026, 7, 25, tzinfo=TZ)


def test_multiple_title_dates_remain_unknown() -> None:
    result = extract_source_time(
        title="比较 2023-01-01 与 2025-01-01",
        content="报告日期：2025-01-01",
    )
    assert result is None


def test_ambiguous_content_keeps_source_time_unknown() -> None:
    result = extract_source_time(content="2024-01-01 旧版；2025-01-01 新版。")
    assert result is None


def test_report_header_date_beats_body_event_and_download_watermark() -> None:
    result = extract_source_time(
        content=(
            "国产模型持续闪耀\n2026 年 7 月 16 日月之暗面发布 Kimi K3。\n"
            "计算机\n行业研究\n2026 年 07 月 18 日\n买入（维持评级）\n"
            "行业周报证券研究报告\n"
            "该报告于2026年07月21日下载，仅供客户使用，请勿传阅。"
        )
    )
    assert result == datetime(2026, 7, 18, tzinfo=TZ)


def test_upload_time_is_never_used_as_source_time() -> None:
    assert extract_source_time(filename="没有日期的文档.pdf", content="无可靠日期") is None
