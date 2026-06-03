"""Aladin used buyback search parser and fetcher."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import httpx
from bs4 import BeautifulSoup

ALADIN_BUYBACK_SEARCH_URL = "https://www.aladin.co.kr/shop/usedshop/wc2b_search.aspx"
ALADIN_GRADES = ("최상", "상", "중")


@dataclass(frozen=True)
class AladinBuybackQuote:
    grade: str
    price: int


@dataclass(frozen=True)
class AladinBuybackResult:
    isbn: str
    availability: str
    quotes: list[AladinBuybackQuote] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)
    raw_status: str = "ok"
    message: str | None = None


def normalize_isbn(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^0-9Xx]", "", value).upper()


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _grade_pattern(grade: str) -> str:
    if grade == "상":
        return r"(?<![가-힣])상(?![가-힣])"
    if grade == "중":
        return r"(?<![가-힣])중(?![가-힣])"
    return re.escape(grade)


def _parse_quotes_from_text(text: str) -> list[AladinBuybackQuote]:
    compact = _compact_text(text)
    quotes: list[AladinBuybackQuote] = []
    for grade in ALADIN_GRADES:
        pattern = rf"{_grade_pattern(grade)}(?:\s|:|：|/|매입가|등급|상태)*([0-9][0-9,]*)\s*원"
        match = re.search(pattern, compact)
        if match:
            quotes.append(AladinBuybackQuote(grade=grade, price=int(match.group(1).replace(",", ""))))
    return quotes


def _not_buying(text: str) -> bool:
    markers = (
        "매입 불가",
        "매입하지 않습니다",
        "매입이 불가능",
        "검색 결과가 없습니다",
        "검색결과가 없습니다",
        "일치하는 상품이 없습니다",
    )
    return any(marker in text for marker in markers)


def parse_aladin_buyback_html(html: str, isbn: str) -> AladinBuybackResult:
    target_isbn = normalize_isbn(isbn)
    soup = BeautifulSoup(html, "html.parser")
    page_text = _compact_text(soup.get_text(" "))
    normalized_page_text = normalize_isbn(page_text)

    if target_isbn and target_isbn not in normalized_page_text:
        if _not_buying(page_text):
            return AladinBuybackResult(isbn=target_isbn, availability="no", raw_status="not_buying", message="매입 불가 또는 결과 없음")
        return AladinBuybackResult(isbn=target_isbn, availability="no", raw_status="isbn_not_found", message="ISBN 일치 결과 없음")

    candidate_texts: list[str] = []
    if target_isbn:
        for node in soup.find_all(string=True):
            if target_isbn not in normalize_isbn(str(node)):
                continue
            parent = getattr(node, "parent", None)
            for _ in range(6):
                if parent is None:
                    break
                text = _compact_text(parent.get_text(" "))
                if text and text not in candidate_texts:
                    candidate_texts.append(text)
                parent = parent.parent

    candidate_texts.append(page_text)
    for text in candidate_texts:
        quotes = _parse_quotes_from_text(text)
        if len(quotes) == len(ALADIN_GRADES):
            return AladinBuybackResult(isbn=target_isbn, availability="yes", quotes=quotes)

    if _not_buying(page_text):
        return AladinBuybackResult(isbn=target_isbn, availability="no", raw_status="not_buying", message="매입 불가 또는 결과 없음")
    return AladinBuybackResult(isbn=target_isbn, availability="error", raw_status="parser_drift", message="상태별 매입가를 찾지 못했습니다")


def should_use_playwright_fallback(result: AladinBuybackResult) -> bool:
    return result.availability == "error" and result.raw_status == "parser_drift"


def fetch_aladin_buyback(
    isbn: str,
    *,
    timeout: float = 10.0,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> AladinBuybackResult:
    target_isbn = normalize_isbn(isbn)
    factory = client_factory or (lambda: httpx.Client(timeout=timeout, follow_redirects=True))
    try:
        with factory() as client:
            response = client.get(ALADIN_BUYBACK_SEARCH_URL, params={"SearchWord": target_isbn})
            response.raise_for_status()
    except httpx.TimeoutException:
        return AladinBuybackResult(isbn=target_isbn, availability="error", raw_status="timeout", message="알라딘 조회 timeout")
    except httpx.HTTPError as exc:
        return AladinBuybackResult(isbn=target_isbn, availability="error", raw_status="http_error", message=str(exc))

    return parse_aladin_buyback_html(response.text, target_isbn)
