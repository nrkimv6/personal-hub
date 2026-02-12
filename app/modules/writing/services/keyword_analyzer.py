"""
Kiwi 형태소 분석기를 사용한 키워드 추출기.

글소스에서 명사를 추출하여 keyword_stats 테이블에 저장.
"""

import logging
import re
from collections import Counter
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import KeywordStats, WritingSource, WritingStopword

logger = logging.getLogger(__name__)

# 추출할 품사 태그
POS_TAGS = {"NNG", "NNP"}  # 일반명사, 고유명사

# 기본 불용어 (DB 외 하드코딩)
DEFAULT_STOPWORDS = {
    "것", "수", "등", "때", "곳", "분", "점", "중", "간", "내", "후", "전", "말",
    "날", "밤", "해", "달", "별", "눈", "손", "발", "몸", "입", "귀", "코",
}


class KeywordAnalyzer:
    """키워드 분석기."""

    def __init__(self, db: Session):
        self.db = db
        self._kiwi = None
        self._stopwords = None

    @property
    def kiwi(self):
        """Kiwi 인스턴스 (lazy loading)."""
        if self._kiwi is None:
            try:
                from kiwipiepy import Kiwi
                logger.info("Kiwi 형태소 분석기 로딩...")
                self._kiwi = Kiwi(num_workers=4)
                logger.info("Kiwi 로딩 완료")
            except ImportError as e:
                logger.error(f"kiwipiepy를 import할 수 없습니다: {e}")
                raise ImportError(
                    "키워드 분석 기능을 사용하려면 kiwipiepy 패키지를 설치해야 합니다. "
                    "설치: pip install kiwipiepy"
                ) from e
        return self._kiwi

    @property
    def stopwords(self) -> set[str]:
        """불용어 세트 (DB + 기본)."""
        if self._stopwords is None:
            db_stopwords = self.db.query(WritingStopword.word).all()
            self._stopwords = DEFAULT_STOPWORDS | {row[0] for row in db_stopwords}
        return self._stopwords

    def _clean_text(self, text: str) -> str:
        """텍스트 정제."""
        text = re.sub(r"<[^>]+>", " ", text)  # HTML 태그
        text = re.sub(r"https?://\S+", " ", text)  # URL
        text = re.sub(r"www\.\S+", " ", text)
        text = re.sub(r"\S+@\S+", " ", text)  # 이메일
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_keywords(self, text: str, min_length: int = 2) -> list[str]:
        """텍스트에서 키워드 추출."""
        text = self._clean_text(text)
        if not text:
            return []

        result = self.kiwi.analyze(text)
        if not result:
            return []

        tokens = result[0][0]  # 첫 번째 분석 결과
        words = []

        for token in tokens:
            word = token.form
            pos = token.tag

            if pos not in POS_TAGS:
                continue
            if len(word) < min_length:
                continue
            if word.isdigit():
                continue
            if word.lower() in self.stopwords:
                continue

            words.append(word)

        return words

    def analyze_all(self, min_freq: int = 3, min_length: int = 2, batch_size: int = 1000) -> dict:
        """전체 소스 분석 (초기 분석용)."""
        # 기존 데이터 삭제
        self.db.query(KeywordStats).filter(KeywordStats.category.is_(None)).delete()
        self.db.commit()

        total_counter = Counter()
        source_counter = Counter()

        total_count = self.db.query(func.count(WritingSource.id)).scalar()
        logger.info(f"총 {total_count:,}건 분석 시작...")

        offset = 0
        processed = 0

        while offset < total_count:
            sources = self.db.query(WritingSource).offset(offset).limit(batch_size).all()

            for source in sources:
                if not source.content:
                    continue

                words = self._extract_keywords(source.content, min_length)
                total_counter.update(words)
                source_counter.update(set(words))
                processed += 1

            offset += batch_size
            logger.info(f"진행: {processed:,}/{total_count:,} ({processed/total_count*100:.1f}%)")

        # 최소 빈도 이상만 필터링
        filtered = {k: v for k, v in total_counter.items() if v >= min_freq}
        logger.info(f"추출된 키워드: {len(total_counter):,} → 필터링 후: {len(filtered):,}")

        # DB에 저장
        analyzed_at = datetime.now()
        for keyword, freq in filtered.items():
            src_count = source_counter.get(keyword, 1)
            avg = round(freq / src_count, 2) if src_count > 0 else freq

            stats = KeywordStats(
                keyword=keyword,
                frequency=freq,
                source_count=src_count,
                avg_per_source=avg,
                analyzed_at=analyzed_at,
            )
            self.db.add(stats)

        self.db.commit()
        logger.info(f"DB 저장 완료: {len(filtered):,}건")

        return {
            "total_sources": total_count,
            "total_keywords": len(total_counter),
            "saved_keywords": len(filtered),
        }

    def analyze_incremental(self, min_freq: int = 3, min_length: int = 2) -> dict:
        """증분 분석 (마지막 분석 이후 추가된 소스만)."""
        last_analyzed = self.db.query(func.max(KeywordStats.analyzed_at)).scalar()

        if last_analyzed:
            new_sources = self.db.query(WritingSource).filter(
                WritingSource.created_at > last_analyzed
            ).all()
        else:
            # 첫 분석
            return self.analyze_all(min_freq, min_length)

        if not new_sources:
            logger.info("분석할 새 소스가 없습니다")
            return {"new_sources": 0, "new_keywords": 0, "updated_keywords": 0}

        logger.info(f"신규 소스 {len(new_sources)}건 분석...")

        total_counter = Counter()
        source_counter = Counter()

        for source in new_sources:
            if not source.content:
                continue
            words = self._extract_keywords(source.content, min_length)
            total_counter.update(words)
            source_counter.update(set(words))

        # 기존 키워드 업데이트 또는 신규 추가
        analyzed_at = datetime.now()
        new_count = 0
        updated_count = 0

        for keyword, freq in total_counter.items():
            if freq < min_freq:
                continue

            existing = self.db.query(KeywordStats).filter_by(keyword=keyword).first()

            if existing:
                existing.frequency += freq
                existing.source_count += source_counter.get(keyword, 0)
                existing.avg_per_source = round(
                    existing.frequency / existing.source_count, 2
                )
                existing.analyzed_at = analyzed_at
                updated_count += 1
            else:
                src_count = source_counter.get(keyword, 1)
                stats = KeywordStats(
                    keyword=keyword,
                    frequency=freq,
                    source_count=src_count,
                    avg_per_source=round(freq / src_count, 2),
                    analyzed_at=analyzed_at,
                )
                self.db.add(stats)
                new_count += 1

        self.db.commit()
        logger.info(f"증분 분석 완료: 신규 {new_count}, 업데이트 {updated_count}")

        return {
            "new_sources": len(new_sources),
            "new_keywords": new_count,
            "updated_keywords": updated_count,
        }
