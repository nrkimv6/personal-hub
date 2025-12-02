"""
브라우저 프로필 마이그레이션 스크립트

기존 브라우저 프로필 디렉토리를 새로운 구조로 이동합니다:
- browser_data/browser_profile -> data/browser_profiles/default

사용법:
    python scripts/migrate_browser_profiles.py

주의사항:
- 브라우저가 실행 중이면 종료 후 실행하세요
- 기존 프로필이 삭제되지 않고 복사됩니다 (안전)
"""

import shutil
from pathlib import Path
import sys
import io

# Windows 콘솔 인코딩 문제 해결
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def migrate_browser_profiles():
    """브라우저 프로필을 새 위치로 마이그레이션"""

    # 프로젝트 루트
    project_root = Path(__file__).parent.parent

    # 소스: 기존 프로필 위치
    old_profile = project_root / "browser_data" / "browser_profile"

    # 타겟: 새 프로필 위치
    new_profile_base = project_root / "data" / "browser_profiles"
    new_default_profile = new_profile_base / "default"

    print("=" * 60)
    print("브라우저 프로필 마이그레이션")
    print("=" * 60)
    print()

    # 1. 기존 프로필 확인
    print(f"1. 기존 프로필 확인: {old_profile}")
    if not old_profile.exists():
        print("   ✗ 기존 프로필이 존재하지 않습니다.")
        print("   → 마이그레이션할 내용이 없습니다.")
        return

    # 파일 개수 확인
    file_count = sum(1 for _ in old_profile.rglob('*') if _.is_file())
    print(f"   ✓ 발견됨 (파일 수: {file_count}개)")
    print()

    # 2. 타겟 디렉토리 준비
    print(f"2. 타겟 디렉토리 준비: {new_default_profile}")

    # 타겟에 이미 파일이 있는지 확인
    if new_default_profile.exists():
        existing_file_count = sum(1 for _ in new_default_profile.rglob('*') if _.is_file())
        if existing_file_count > 0:
            print(f"   ⚠ 타겟에 이미 파일이 존재합니다 (파일 수: {existing_file_count}개)")
            print("   → 기존 파일 위에 덮어씁니다 (병합 모드)")
            # 백업은 하지 않고 바로 덮어쓰기 (파일이 중복되면 덮어쓰기)

    # 타겟 디렉토리 생성
    new_profile_base.mkdir(parents=True, exist_ok=True)
    new_default_profile.mkdir(exist_ok=True)
    print(f"   ✓ 디렉토리 생성 완료")
    print()

    # 3. 프로필 복사
    print("3. 프로필 복사 중...")
    print(f"   {old_profile}")
    print(f"   → {new_default_profile}")

    # 파일 복사 (디렉토리 구조 유지)
    copied_count = 0
    skipped_count = 0
    skipped_files = []

    for item in old_profile.rglob('*'):
        if item.is_file():
            # 상대 경로 계산
            rel_path = item.relative_to(old_profile)
            target_path = new_default_profile / rel_path

            try:
                # 타겟 디렉토리 생성
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # 파일 복사
                shutil.copy2(item, target_path)
                copied_count += 1

                # 진행 상황 표시 (100개마다)
                if copied_count % 100 == 0:
                    print(f"   복사 중... {copied_count}개 완료")

            except (PermissionError, OSError) as e:
                # 파일이 사용 중이거나 접근 불가능한 경우 건너뛰기
                skipped_count += 1
                skipped_files.append(str(rel_path))
                if skipped_count <= 5:  # 처음 5개만 출력
                    print(f"   ⚠ 건너뜀: {rel_path} ({str(e)[:50]})")

    print(f"   ✓ 총 {copied_count}개 파일 복사 완료")
    if skipped_count > 0:
        print(f"   ⚠ {skipped_count}개 파일 건너뜀 (브라우저가 사용 중)")
        if skipped_count > 5:
            print(f"      (처음 5개만 표시, 총 {skipped_count}개)")
    print()

    # 4. 검증
    print("4. 검증 중...")
    new_file_count = sum(1 for _ in new_default_profile.rglob('*') if _.is_file())
    print(f"   기존: {file_count}개 파일")
    print(f"   복사됨: {new_file_count}개 파일")
    print(f"   건너뜀: {skipped_count}개 파일")

    expected_count = file_count - skipped_count
    if new_file_count == expected_count:
        print("   ✓ 검증 성공!")
    elif new_file_count >= expected_count * 0.9:  # 90% 이상 복사되면 성공으로 간주
        print(f"   ✓ 대부분 복사됨 ({new_file_count}/{expected_count})")
    else:
        print(f"   ⚠ 파일 수가 예상과 다릅니다 (차이: {abs(new_file_count - expected_count)}개)")
    print()

    # 5. 완료
    print("=" * 60)
    print("마이그레이션 완료!")
    print("=" * 60)
    print()
    print("다음 단계:")
    print(f"1. 새 프로필 확인: {new_default_profile}")
    print(f"2. 기존 프로필은 안전을 위해 그대로 유지됩니다: {old_profile}")

    if skipped_count > 0:
        print()
        print("⚠️ 주의사항:")
        print(f"  - {skipped_count}개 파일이 건너뛰어졌습니다 (브라우저 사용 중)")
        print("  - 브라우저를 완전히 종료한 후 다시 실행하면 모든 파일을 복사할 수 있습니다")
        print("  - 또는 브라우저를 종료한 후 수동으로 남은 파일을 복사하세요")

    print()
    print("3. 브라우저를 실행하여 프로필이 정상 작동하는지 확인하세요")
    print("4. 정상 작동 확인 후 기존 프로필을 수동으로 삭제하세요")
    print()

if __name__ == "__main__":
    print()
    print("⚠️ 브라우저가 실행 중이면 종료 후 진행하세요!")
    print()

    response = input("계속하시겠습니까? (y/N): ")
    if response.lower() != 'y':
        print("마이그레이션이 취소되었습니다.")
        sys.exit(0)

    print()
    migrate_browser_profiles()
