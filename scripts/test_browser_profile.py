"""
브라우저 프로필 로딩 테스트 스크립트

새로운 프로필 구조가 제대로 작동하는지 확인합니다.

사용법:
    python scripts/test_browser_profile.py
"""

import sys
import asyncio
from pathlib import Path
import io

# Windows 콘솔 인코딩 문제 해결
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings, logger
from app.database import SessionLocal
from app.services.account_service import account_service
from app.services.browser_service import BrowserService


async def test_browser_profile():
    """브라우저 프로필 로딩 테스트"""

    print("=" * 60)
    print("브라우저 프로필 로딩 테스트")
    print("=" * 60)
    print()

    # 1. 설정 확인
    print("1. 설정 확인")
    print(f"   DATA_DIR: {settings.DATA_DIR}")
    print(f"   BROWSER_PROFILES_DIR: {settings.BROWSER_PROFILES_DIR}")
    print(f"   DEFAULT_PROFILE_NAME: {settings.DEFAULT_PROFILE_NAME}")
    print(f"   프로필 전체 경로: {Path(settings.DATA_DIR) / settings.BROWSER_PROFILES_DIR / settings.DEFAULT_PROFILE_NAME}")
    print()

    # 2. DB에서 계정 확인
    print("2. 데이터베이스 계정 확인")
    db = SessionLocal()
    try:
        accounts = account_service.get_all(db)
        print(f"   총 계정 수: {len(accounts)}")
        for account in accounts:
            print(f"   - {account.name} (ID: {account.id})")
            print(f"     profile_dir: {account.profile_dir}")
            print(f"     profile_path: {account.profile_path}")
            print(f"     is_active: {account.is_active}")
            print(f"     is_logged_in: {account.is_logged_in}")

            # 프로필 디렉토리 존재 확인
            profile_path = Path(account.profile_path)
            if profile_path.exists():
                file_count = sum(1 for _ in profile_path.rglob('*') if _.is_file())
                print(f"     ✓ 디렉토리 존재 (파일 수: {file_count})")
            else:
                print(f"     ✗ 디렉토리 없음")
            print()
    finally:
        db.close()

    # 3. 브라우저 서비스 초기화 테스트
    print("3. 브라우저 서비스 초기화 테스트")
    browser_service = BrowserService()

    # 기본 계정으로 컨텍스트 생성 시도
    print("   기본 계정으로 브라우저 컨텍스트 생성 중...")
    try:
        context = await browser_service.get_or_create_context(service_account_id=None)
        print(f"   ✓ 브라우저 컨텍스트 생성 성공")
        print(f"   컨텍스트 정보: {context}")

        # 테스트 페이지 열기
        print()
        print("4. 테스트 페이지 열기")
        print("   네이버 홈페이지를 열어봅니다...")
        page = await context.new_page()
        await page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=30000)
        print(f"   ✓ 페이지 로드 성공")
        print(f"   페이지 제목: {await page.title()}")

        # 5초 대기 (확인용)
        print()
        print("   5초 후 브라우저를 닫습니다...")
        await asyncio.sleep(5)

        # 정리
        await page.close()
        print("   ✓ 페이지 닫기 완료")

    except Exception as e:
        print(f"   ✗ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 브라우저 종료
        if browser_service.playwright_instance:
            try:
                await browser_service.playwright_instance.stop()
                print("   ✓ 브라우저 인스턴스 종료 완료")
            except Exception as e:
                print(f"   ⚠ 브라우저 종료 중 오류: {e}")

    print()
    print("=" * 60)
    print("테스트 완료!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_browser_profile())
