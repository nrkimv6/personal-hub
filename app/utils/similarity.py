"""
유사도 계산 유틸리티 함수들

이벤트/팝업 중복 감지를 위한 텍스트 및 데이터 유사도 계산
"""
import re
from datetime import date
from typing import List, Optional, Set


def normalize(text: str) -> str:
    """텍스트 정규화 (대소문자, 공백, 특수문자)

    Args:
        text: 정규화할 텍스트

    Returns:
        정규화된 텍스트
    """
    if not text:
        return ""
    # 소문자 변환, 공백/특수문자 제거
    return re.sub(r'\s+', '', text.lower().strip())


def normalize_url(url: str) -> str:
    """URL 정규화 (프로토콜, www, 쿼리스트링 제거)

    Args:
        url: 정규화할 URL

    Returns:
        정규화된 URL
    """
    if not url:
        return ""
    # 프로토콜 및 www 제거
    url = re.sub(r'^https?://(www\.)?', '', url.lower())
    # 쿼리스트링 제거
    url = url.split('?')[0].rstrip('/')
    return url


def dates_overlap(
    start1: Optional[date],
    end1: Optional[date],
    start2: Optional[date],
    end2: Optional[date]
) -> bool:
    """날짜 범위 중복 확인

    Args:
        start1: 첫 번째 범위 시작일
        end1: 첫 번째 범위 종료일
        start2: 두 번째 범위 시작일
        end2: 두 번째 범위 종료일

    Returns:
        두 범위가 겹치면 True
    """
    # 모든 날짜가 있어야 비교 가능
    if not all([start1, end1, start2, end2]):
        return False
    # 겹치지 않는 조건의 역
    return not (end1 < start2 or end2 < start1)


def jaccard_similarity(list1: List[str], list2: List[str]) -> float:
    """Jaccard 유사도 (집합 비교)

    Args:
        list1: 첫 번째 리스트
        list2: 두 번째 리스트

    Returns:
        0.0 ~ 1.0 사이의 유사도
    """
    if not list1 or not list2:
        return 0.0

    # 정규화하여 비교
    set1 = {normalize(item) for item in list1 if item}
    set2 = {normalize(item) for item in list2 if item}

    if not set1 or not set2:
        return 0.0

    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def text_similarity(text1: str, text2: str) -> float:
    """텍스트 유사도 (토큰 기반 Jaccard)

    Args:
        text1: 첫 번째 텍스트
        text2: 두 번째 텍스트

    Returns:
        0.0 ~ 1.0 사이의 유사도
    """
    if not text1 or not text2:
        return 0.0

    # 한국어와 영어 모두 처리하기 위해 공백으로 분리 후 정규화
    def tokenize(text: str) -> Set[str]:
        # 특수문자 제거 후 공백으로 분리
        cleaned = re.sub(r'[^\w\s]', ' ', text.lower())
        tokens = cleaned.split()
        # 빈 토큰 제거
        return {t for t in tokens if len(t) > 1}

    tokens1 = tokenize(text1)
    tokens2 = tokenize(text2)

    if not tokens1 or not tokens2:
        return 0.0

    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    return intersection / union if union > 0 else 0.0


def compare_address(addr1: str, addr2: str) -> float:
    """주소 유사도 (시/구/동 추출 비교)

    TODO: 주소 정규화 라이브러리 사용 고려

    Args:
        addr1: 첫 번째 주소
        addr2: 두 번째 주소

    Returns:
        0.0 ~ 1.0 사이의 유사도
    """
    if not addr1 or not addr2:
        return 0.0

    # 간단한 토큰 비교 방식
    # 향후 juso.go.kr API 등을 활용한 정규화 가능
    return text_similarity(addr1, addr2)


def extract_korean_brand(text: str) -> str:
    """텍스트에서 브랜드명 추출 (정규화)

    Args:
        text: 브랜드명이 포함된 텍스트

    Returns:
        정규화된 브랜드명
    """
    if not text:
        return ""

    # 공백, 특수문자 제거
    brand = re.sub(r'[\s\-_\.]+', '', text.lower())

    # 일반적인 접미사 제거
    suffixes = ['코리아', 'korea', '공식', 'official', '스토어', 'store', '샵', 'shop']
    for suffix in suffixes:
        if brand.endswith(suffix):
            brand = brand[:-len(suffix)]

    return brand
