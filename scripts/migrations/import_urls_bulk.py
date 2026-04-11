"""
URL 목록을 크롤링 요청 큐에 일괄 추가하는 스크립트

실행 방법:
    cd D:\work\project\tools\monitor-page
    .\.venv\Scripts\Activate.ps1
    python scripts/import_urls_bulk.py

옵션:
    --dry-run    실제 삽입 없이 파싱 결과만 확인
    --file PATH  입력 파일 경로 (기본: data/2025-12-24_original_files.md)
"""

import re
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.crawl_request import CrawlRequest
from app.config import settings


# URL 타입 상수
URL_TYPE_INSTAGRAM_POST = "instagram_post"
URL_TYPE_INSTAGRAM_REEL = "instagram_reel"


def extract_instagram_urls(file_path: Path) -> list[dict]:
    """마크다운 파일에서 Instagram URL 추출"""
    content = file_path.read_text(encoding="utf-8")

    # Instagram URL 패턴
    patterns = [
        # 일반 게시물: /p/ID/
        (r'https://www\.instagram\.com/(?:[^/]+/)?p/([A-Za-z0-9_-]+)/?', URL_TYPE_INSTAGRAM_POST),
        # 릴스: /reel/ID/
        (r'https://www\.instagram\.com/(?:[^/]+/)?reel/([A-Za-z0-9_-]+)/?', URL_TYPE_INSTAGRAM_REEL),
    ]

    results = []
    seen_urls = set()

    for pattern, url_type in patterns:
        for match in re.finditer(pattern, content):
            url = match.group(0).rstrip('/')
            # URL 정규화 (계정명 포함된 URL을 표준 형식으로)
            post_id = match.group(1)
            if url_type == URL_TYPE_INSTAGRAM_POST:
                normalized_url = f'https://www.instagram.com/p/{post_id}/'
            else:
                normalized_url = f'https://www.instagram.com/reel/{post_id}/'

            if normalized_url not in seen_urls:
                seen_urls.add(normalized_url)
                results.append({
                    'url': normalized_url,
                    'url_type': url_type,
                    'post_id': post_id
                })

    return results


def import_urls(urls: list[dict], dry_run: bool = False):
    """URL들을 크롤링 요청 테이블에 삽입"""

    # DB 연결
    db_path = project_root / "data" / "monitor.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # 이미 존재하는 URL 확인
        existing = session.query(CrawlRequest.url).filter(
            CrawlRequest.url.in_([u['url'] for u in urls])
        ).all()
        existing_urls = {r[0] for r in existing}

        new_urls = [u for u in urls if u['url'] not in existing_urls]

        print(f"\n=== 요약 ===")
        print(f"총 추출된 URL: {len(urls)}")
        print(f"이미 존재하는 URL: {len(existing_urls)}")
        print(f"새로 추가할 URL: {len(new_urls)}")

        if dry_run:
            print("\n[DRY RUN] 실제 삽입하지 않습니다.")
            print("\n처음 10개 URL 미리보기:")
            for u in new_urls[:10]:
                print(f"  - [{u['url_type']}] {u['url']}")
            return

        if not new_urls:
            print("\n추가할 새 URL이 없습니다.")
            return

        # 요청 레코드 생성
        now = datetime.now()
        requests = []
        for u in new_urls:
            req = CrawlRequest(
                url=u['url'],
                url_type=u['url_type'],
                status=CrawlRequest.STATUS_PENDING,
                requested_at=now,
                requested_by="bulk_import"
            )
            requests.append(req)

        session.bulk_save_objects(requests)
        session.commit()

        print(f"\n✓ {len(requests)}개 크롤링 요청이 추가되었습니다.")
        print("워커가 실행 중이면 순차적으로 처리됩니다.")

    finally:
        session.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="URL 목록을 크롤링 요청 큐에 일괄 추가")
    parser.add_argument("--dry-run", action="store_true", help="실제 삽입 없이 파싱 결과만 확인")
    parser.add_argument("--file", type=str, default="data/2025-12-24_original_files.md", help="입력 파일 경로")
    args = parser.parse_args()

    file_path = project_root / args.file

    if not file_path.exists():
        print(f"파일을 찾을 수 없습니다: {file_path}")
        sys.exit(1)

    print(f"파일 읽는 중: {file_path}")

    # URL 추출
    urls = extract_instagram_urls(file_path)
    print(f"Instagram URL {len(urls)}개 추출됨")

    # URL 타입별 통계
    by_type = {}
    for u in urls:
        by_type[u['url_type']] = by_type.get(u['url_type'], 0) + 1

    print("\nURL 타입별 수:")
    for url_type, count in by_type.items():
        print(f"  - {url_type}: {count}개")

    # 삽입
    import_urls(urls, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
