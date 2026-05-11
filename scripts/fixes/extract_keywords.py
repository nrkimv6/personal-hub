"""
Kiwi 형태소 분석기를 사용한 키워드 추출 스크립트 (SQLite 전용 레거시).

⚠️ LEGACY: 이 스크립트는 SQLite data/monitor.db 직접 접근을 사용합니다.
   2026-04-10 PostgreSQL 전환 이후에는 실행하기 전 --sqlite-path 옵션으로
   별도 SQLite 파일 경로를 명시해야 합니다.
   기본값(data/monitor.db)이 없으면 스크립트가 종료됩니다.

Usage:
    python scripts/fixes/extract_keywords.py --sqlite-path data/monitor.db
    python scripts/fixes/extract_keywords.py --sqlite-path data/monitor.db --min-freq 5
    python scripts/fixes/extract_keywords.py --sqlite-path data/monitor.db --min-length 2
    python scripts/fixes/extract_keywords.py --sqlite-path data/monitor.db --pos NNG,NNP
"""

import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from kiwipiepy import Kiwi

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Kiwi 품사 태그 (추출할 것들)
# NNG: 일반명사, NNP: 고유명사, NNB: 의존명사
# VV: 동사, VA: 형용사, VX: 보조용언
# https://github.com/bab2min/kiwipiepy#%ED%92%88%EC%82%AC-%ED%83%9C%EA%B7%B8
DEFAULT_POS_TAGS = {"NNG", "NNP"}  # 기본: 명사만

# 블로그 템플릿/UI 관련 불용어
TEMPLATE_STOPWORDS = {
    "스크랩", "인쇄", "확인", "친구신청", "영상시", "무화과", "글빛사랑",
    "좋은글中에", "좋은글중에", "카테고리", "블로그", "댓글", "공감", "구독",
    "이웃", "팔로우", "공유", "신고", "수정", "삭제", "목록", "이전", "다음",
    "http", "https", "www", "com", "net", "org", "html", "blog", "naver", "daum",
    "tistory", "category",
}

# 일반 불용어 (의미 없는 단어들)
GENERAL_STOPWORDS = {
    "것", "수", "등", "때", "곳", "분", "점", "중", "간", "내", "후", "전", "말",
    "날", "밤", "해", "달", "별", "눈", "손", "발", "몸", "입", "귀", "코",
}


def clean_text(text: str) -> str:
    """텍스트 정제: HTML, URL 제거."""
    # HTML 태그 제거
    text = re.sub(r"<[^>]+>", " ", text)
    # URL 제거
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"www\.\S+", " ", text)
    # 이메일 제거
    text = re.sub(r"\S+@\S+", " ", text)
    # 연속 공백 제거
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def analyze_keywords(
    min_freq: int = 3,
    min_length: int = 2,
    pos_tags: set[str] | None = None,
    batch_size: int = 1000,
    sqlite_path: Path | None = None,
):
    """Kiwi로 형태소 분석 후 키워드 추출."""
    if pos_tags is None:
        pos_tags = DEFAULT_POS_TAGS

    db_path = sqlite_path or (PROJECT_ROOT / "data" / "monitor.db")
    if not db_path.exists():
        print(f"❌ SQLite DB를 찾을 수 없습니다: {db_path}")
        print("이 스크립트는 SQLite 전용 레거시입니다. --sqlite-path 옵션으로 경로를 명시하세요.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 기존 데이터 삭제 (재분석 시)
    cursor.execute("DELETE FROM keyword_stats WHERE category IS NULL")
    conn.commit()

    print(f"DB: {db_path}")
    print(f"설정: min_freq={min_freq}, min_length={min_length}, pos={pos_tags}")
    print("-" * 50)

    # Kiwi 초기화 (멀티스레드)
    print("Kiwi 형태소 분석기 로딩...")
    kiwi = Kiwi(num_workers=4)  # 4코어 사용
    print("Kiwi 로딩 완료!")

    # 전체 빈도수 카운터
    total_counter = Counter()
    # 각 키워드가 몇 개의 글에서 나왔는지
    source_counter = Counter()

    # 데이터 로드
    cursor.execute("SELECT COUNT(*) FROM writing_sources")
    total_count = cursor.fetchone()[0]
    print(f"총 {total_count:,}건 분석 시작...")

    offset = 0
    processed = 0

    while offset < total_count:
        cursor.execute(
            "SELECT id, content FROM writing_sources LIMIT ? OFFSET ?",
            (batch_size, offset)
        )
        rows = cursor.fetchall()

        # 배치 텍스트 준비
        texts = []
        for source_id, content in rows:
            if content:
                texts.append(clean_text(content))
            else:
                texts.append("")

        # Kiwi 배치 분석
        results = kiwi.analyze(texts)

        for i, result in enumerate(results):
            # result는 [(tokens, score), ...] 형태
            tokens = result[0][0] if result else []
            words = []
            for token in tokens:
                word = token.form
                pos = token.tag

                # 품사 필터
                if pos not in pos_tags:
                    continue

                # 길이 필터
                if len(word) < min_length:
                    continue

                # 숫자만 있는 경우 제외
                if word.isdigit():
                    continue

                # 불용어 제외
                if word.lower() in TEMPLATE_STOPWORDS or word in GENERAL_STOPWORDS:
                    continue

                words.append(word)

            total_counter.update(words)
            source_counter.update(set(words))
            processed += 1

        offset += batch_size
        print(f"  진행: {processed:,}/{total_count:,} ({processed/total_count*100:.1f}%)")

    print("-" * 50)
    print(f"추출된 고유 키워드: {len(total_counter):,}개")

    # 최소 빈도 이상만 필터링
    filtered = {k: v for k, v in total_counter.items() if v >= min_freq}
    print(f"최소 빈도({min_freq}) 이상: {len(filtered):,}개")

    # DB에 저장
    analyzed_at = datetime.now().isoformat()
    insert_data = []

    for keyword, freq in filtered.items():
        src_count = source_counter.get(keyword, 1)
        avg = round(freq / src_count, 2) if src_count > 0 else freq
        insert_data.append((keyword, freq, src_count, avg, None, analyzed_at))

    cursor.executemany(
        """
        INSERT INTO keyword_stats (keyword, frequency, source_count, avg_per_source, category, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        insert_data
    )
    conn.commit()

    print(f"DB 저장 완료: {len(insert_data):,}건")

    # 상위 50개 출력 (파일로)
    print("-" * 50)
    cursor.execute(
        "SELECT keyword, frequency, source_count FROM keyword_stats ORDER BY frequency DESC LIMIT 50"
    )
    rows = cursor.fetchall()

    output_file = PROJECT_ROOT / "data" / "keyword_top50.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("순위\t키워드\t빈도수\t글 수\n")
        f.write("-" * 40 + "\n")
        for i, (kw, freq, src) in enumerate(rows, 1):
            f.write(f"{i}\t{kw}\t{freq:,}\t{src:,}\n")

    print(f"상위 50개 키워드: {output_file}")

    conn.close()
    print("-" * 50)
    print("완료!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kiwi 형태소 분석 기반 키워드 추출 (SQLite 레거시)")
    parser.add_argument("--min-freq", type=int, default=3, help="최소 빈도수 (기본: 3)")
    parser.add_argument("--min-length", type=int, default=2, help="최소 글자수 (기본: 2)")
    parser.add_argument(
        "--pos", type=str, default="NNG,NNP",
        help="추출할 품사 (기본: NNG,NNP = 일반명사,고유명사)"
    )
    parser.add_argument("--sqlite-path", type=str, default=None, help="SQLite DB 경로 (기본: data/monitor.db)")

    args = parser.parse_args()
    pos_tags = set(args.pos.split(","))
    sqlite_path = Path(args.sqlite_path) if args.sqlite_path else None
    analyze_keywords(min_freq=args.min_freq, min_length=args.min_length, pos_tags=pos_tags, sqlite_path=sqlite_path)
