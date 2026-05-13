from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class ParsedItem:
    title: str
    url: str
    duration_minutes: Optional[int]


@dataclass
class ParseResult:
    items: list[ParsedItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_duration(text: str) -> Optional[int]:
    """분 단위 정수로 변환.

    지원 형식:
    - "15 minutes" → 15
    - "1 hour" → 60
    - "1 hour 45 minutes" → 105
    - "8 hours 30 min" → 510
    - "30 mins" → 30
    - 숫자만 있으면 그대로 int
    - 파싱 불가면 None
    """
    text = text.strip()
    if not text:
        return None

    # 숫자만 있는 경우
    if re.fullmatch(r"\d+", text):
        return int(text)

    total = 0
    matched = False

    # hours 패턴
    hour_match = re.search(r"(\d+)\s*hour(?:s)?", text, re.IGNORECASE)
    if hour_match:
        total += int(hour_match.group(1)) * 60
        matched = True

    # minutes 패턴 (minute, minutes, min, mins)
    min_match = re.search(r"(\d+)\s*min(?:utes?|s)?(?!\w)", text, re.IGNORECASE)
    if min_match:
        total += int(min_match.group(1))
        matched = True

    if matched:
        return total

    return None


def parse_markdown_table(text: str) -> ParseResult:
    """Markdown 표에서 학습 항목을 파싱.

    파싱 규칙:
    1. | ... | 형식 행만 처리 (헤더/구분선 제외)
    2. 각 셀에서 [title](url) 패턴으로 제목+링크 추출
    3. 못 찾으면 https:// 로 시작하는 URL fallback
    4. URL 없는 행은 errors에 추가하고 건너뜀
    5. duration은 행의 모든 셀에서 _parse_duration 시도, 첫 번째 성공값 사용
    6. 불완전 행(URL 없음)은 errors에 추가하되 전체 실패시키지 않음
    """
    result = ParseResult()

    # | ... | 형식인 행만 추출
    table_row_pattern = re.compile(r"^\s*\|(.+)\|\s*$")
    # 구분선 패턴: |---|---|, | :---: | 등
    separator_pattern = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
    # 마크다운 링크 패턴
    md_link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    # URL 패턴
    url_pattern = re.compile(r"https?://\S+")

    lines = text.splitlines()
    # 구분선 바로 앞 행 인덱스를 header_indices로 수집 (헤더 행 스킵용)
    header_indices: set[int] = set()
    for i, line in enumerate(lines):
        if separator_pattern.match(line) and i > 0:
            header_indices.add(i - 1)

    for line_num, line in enumerate(lines, start=1):
        row_match = table_row_pattern.match(line)
        if not row_match:
            continue

        # 구분선 건너뜀
        if separator_pattern.match(line):
            continue

        # 헤더 행 건너뜀 (구분선 바로 앞 행)
        if (line_num - 1) in header_indices:
            continue

        # 셀 분리
        cells_raw = row_match.group(1)
        cells = [c.strip() for c in cells_raw.split("|")]

        # [title](url) 패턴 탐색
        title: Optional[str] = None
        url: Optional[str] = None

        for cell in cells:
            link_match = md_link_pattern.search(cell)
            if link_match:
                title = link_match.group(1).strip()
                url = link_match.group(2).strip()
                break

        # fallback: https:// URL 탐색
        if url is None:
            for cell in cells:
                url_match = url_pattern.search(cell)
                if url_match:
                    url = url_match.group(0).strip()
                    # title은 URL 자체로 설정
                    if title is None:
                        title = url
                    break

        if url is None:
            result.errors.append(f"Line {line_num}: URL을 찾을 수 없음 — {line.strip()!r}")
            continue

        if title is None:
            title = url

        # duration 파싱: 모든 셀에서 첫 번째 성공값
        duration: Optional[int] = None
        for cell in cells:
            parsed = _parse_duration(cell)
            if parsed is not None:
                duration = parsed
                break

        result.items.append(ParsedItem(title=title, url=url, duration_minutes=duration))

    return result
