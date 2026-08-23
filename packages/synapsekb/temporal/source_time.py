from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SEPARATED_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>19\d{2}|20\d{2})"
    r"\s*(?:年|[._\-/])\s*(?P<month>0?[1-9]|1[0-2])"
    r"\s*(?:月|[._\-/])\s*(?P<day>0?[1-9]|[12]\d|3[01])\s*日?(?!\d)"
)
COMPACT_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<year>19\d{2}|20\d{2})"
    r"(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])(?!\d)"
)
SOURCE_TIME_LABEL_PATTERN = re.compile(
    r"(?:发布日期|发布时间|报告日期|报告时间|会议日期|会议时间|生效日期|签发日期|"
    r"成文日期|更新日期|publication\s+date|published(?:\s+on)?|report\s+date|date)"
    r"\s*[:：]?\s*$",
    re.IGNORECASE,
)
REPORT_HEADER_PATTERN = re.compile(
    r"(?:行业研究|公司研究|证券研究报告|行业周报|公司报告|研究报告|评级)",
    re.IGNORECASE,
)
DOWNLOAD_WATERMARK_PATTERN = re.compile(
    r"(?:下载|下载时间|仅供.{0,30}使用|请勿传阅)",
    re.IGNORECASE,
)
CONTENT_HEAD_CHARS = 12_000
EARLY_COVER_CHARS = 800


@dataclass(frozen=True, slots=True)
class _DateCandidate:
    value: datetime
    start: int
    end: int


def _candidate_from_match(
    match: re.Match[str],
    timezone: str,
) -> _DateCandidate | None:
    try:
        value = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            tzinfo=ZoneInfo(timezone),
        )
    except ValueError:
        return None
    return _DateCandidate(value=value, start=match.start(), end=match.end())


def _date_candidates(value: str, timezone: str) -> list[_DateCandidate]:
    candidates: list[_DateCandidate] = []
    for pattern in (SEPARATED_DATE_PATTERN, COMPACT_DATE_PATTERN):
        for match in pattern.finditer(value):
            candidate = _candidate_from_match(match, timezone)
            if candidate is not None:
                candidates.append(candidate)
    return sorted(candidates, key=lambda candidate: candidate.start)


def _distinct_dates(value: str | None, timezone: str) -> set[datetime]:
    if not value:
        return set()
    return {candidate.value for candidate in _date_candidates(value, timezone)}


def parse_explicit_date(value: str, timezone: str = "Asia/Shanghai") -> datetime | None:
    candidates = _date_candidates(value, timezone)
    return candidates[0].value if candidates else None


def extract_source_time(
    *,
    explicit: datetime | None = None,
    file_metadata_time: datetime | None = None,
    filename: str | None = None,
    title: str | None = None,
    content: str | None = None,
    timezone: str = "Asia/Shanghai",
) -> datetime | None:
    """Apply the product's strict source-time priority.

    Filename and title dates must be unambiguous. Content inspection is restricted
    to the leading material and accepts labelled, cover-positioned, or clearly
    dominant full dates. A bare year, conflicting evidence, or missing evidence
    yields None.
    """

    if explicit is not None:
        return explicit
    if file_metadata_time is not None:
        return file_metadata_time
    if filename:
        filename_dates = _distinct_dates(Path(filename).stem, timezone)
        if len(filename_dates) == 1:
            return next(iter(filename_dates))
        if len(filename_dates) > 1:
            return None
    title_dates = _distinct_dates(title, timezone)
    if len(title_dates) == 1:
        return next(iter(title_dates))
    if len(title_dates) > 1:
        return None
    if not content:
        return None

    head = content[:CONTENT_HEAD_CHARS]
    candidates = _date_candidates(head, timezone)
    if not candidates:
        return None

    labelled = {
        candidate.value
        for candidate in candidates
        if SOURCE_TIME_LABEL_PATTERN.search(head[max(0, candidate.start - 40) : candidate.start])
    }
    if len(labelled) == 1:
        return next(iter(labelled))
    if len(labelled) > 1:
        return None

    report_header_scores: dict[datetime, int] = {}
    for index, candidate in enumerate(candidates):
        next_candidate_start = (
            candidates[index + 1].start if index + 1 < len(candidates) else len(head)
        )
        watermark_window = head[
            max(0, candidate.start - 30) : min(next_candidate_start, candidate.start + 120)
        ]
        if DOWNLOAD_WATERMARK_PATTERN.search(watermark_window):
            continue
        before_window = head[max(0, candidate.start - 60) : candidate.start]
        after_window = head[candidate.end : candidate.end + 80]
        score = 0
        if REPORT_HEADER_PATTERN.search(before_window):
            score += 3
        if REPORT_HEADER_PATTERN.search(after_window):
            score += 2
        if head[candidate.end : candidate.end + 4].lstrip(" \t").startswith(("\n", "\r")):
            score += 1
        if score:
            report_header_scores[candidate.value] = max(
                score,
                report_header_scores.get(candidate.value, 0),
            )
    if report_header_scores:
        best_score = max(report_header_scores.values())
        best_dates = {
            value for value, score in report_header_scores.items() if score == best_score
        }
        if best_score >= 3 and len(best_dates) == 1:
            return next(iter(best_dates))
        if best_score >= 3 and len(best_dates) > 1:
            return None

    early = [candidate for candidate in candidates if candidate.start < EARLY_COVER_CHARS]
    early_distinct = {candidate.value for candidate in early}
    if len(early_distinct) == 1:
        return next(iter(early_distinct))

    counts = Counter(candidate.value for candidate in candidates)
    if len(counts) == 1:
        return next(iter(counts))
    (best, best_count), (_, second_count) = counts.most_common(2)
    total = sum(counts.values())
    first_best_position = next(
        candidate.start for candidate in candidates if candidate.value == best
    )
    if (
        best_count >= 2
        and best_count >= second_count * 2
        and best_count / total >= 0.6
        and first_best_position < 2_000
    ):
        return best
    return None
