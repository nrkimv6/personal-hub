"""
브라우저 프로필 설정 확인 스크립트

DB 연결 없이 설정과 파일 시스템만 확인합니다.

사용법:
    python scripts/check_profile_config.py
"""

import sys
from pathlib import Path
import io

# Windows 콘솔 인코딩 문제 해결
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def check_profile_configuration():
    """프로필 설정 확인"""

    print("=" * 60)
    print("브라우저 프로필 설정 확인")
    print("=" * 60)
    print()

    # 1. config.py에서 설정값 읽기
    print("1. 설정 확인 (config.py)")
    try:
        # 직접 파일 읽기
        config_file = project_root / "app" / "config.py"

        settings_dict = {}
        with open(config_file, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    if 'DATA_DIR' in line and ':' in line:
                        # DATA_DIR: str = "./data" 형태
                        if '=' in line:
                            value = line.split('=')[1].strip()
                            value = value.strip('"').strip("'")
                            if value.endswith('# 데이터 저장 디렉토리 (DB, 브라우저 프로필 등)'):
                                value = value.split('#')[0].strip().strip('"').strip("'")
                            settings_dict['DATA_DIR'] = value
                    elif 'BROWSER_PROFILES_DIR' in line and ':' in line:
                        if '=' in line:
                            value = line.split('=')[1].strip()
                            value = value.strip('"').strip("'")
                            if '#' in value:
                                value = value.split('#')[0].strip().strip('"').strip("'")
                            settings_dict['BROWSER_PROFILES_DIR'] = value
                    elif 'DEFAULT_PROFILE_NAME' in line and ':' in line:
                        if '=' in line:
                            value = line.split('=')[1].strip()
                            value = value.strip('"').strip("'")
                            if '#' in value:
                                value = value.split('#')[0].strip().strip('"').strip("'")
                            settings_dict['DEFAULT_PROFILE_NAME'] = value

        data_dir = settings_dict.get('DATA_DIR', './data')
        profiles_dir = settings_dict.get('BROWSER_PROFILES_DIR', 'browser_profiles')
        default_name = settings_dict.get('DEFAULT_PROFILE_NAME', 'default')

        print(f"   DATA_DIR: {data_dir}")
        print(f"   BROWSER_PROFILES_DIR: {profiles_dir}")
        print(f"   DEFAULT_PROFILE_NAME: {default_name}")
        print()

        # 2. 실제 경로 확인
        print("2. 프로필 디렉토리 확인")
        profile_base = project_root / data_dir / profiles_dir
        default_profile = profile_base / default_name

        print(f"   프로필 베이스: {profile_base}")
        print(f"   기본 프로필: {default_profile}")
        print()

        # 3. 디렉토리 존재 및 파일 확인
        print("3. 파일 시스템 확인")

        if profile_base.exists():
            print(f"   ✓ 프로필 베이스 디렉토리 존재")

            # 프로필 목록
            profiles = [d for d in profile_base.iterdir() if d.is_dir() and not d.name.startswith('.')]
            print(f"   발견된 프로필: {len(profiles)}개")

            for profile in profiles:
                file_count = sum(1 for _ in profile.rglob('*') if _.is_file())
                print(f"     - {profile.name}: {file_count}개 파일")
        else:
            print(f"   ✗ 프로필 베이스 디렉토리 없음: {profile_base}")

        print()

        if default_profile.exists():
            file_count = sum(1 for _ in default_profile.rglob('*') if _.is_file())
            print(f"   ✓ 기본 프로필 디렉토리 존재 ({file_count}개 파일)")

            # 주요 파일 확인
            important_files = [
                'Default/Preferences',
                'Default/History',
                'Default/Cookies',
                'Local State',
            ]

            print(f"   주요 파일 확인:")
            for file_rel in important_files:
                file_path = default_profile / file_rel
                if file_path.exists():
                    size = file_path.stat().st_size
                    print(f"     ✓ {file_rel} ({size:,} bytes)")
                else:
                    print(f"     ✗ {file_rel} (없음)")
        else:
            print(f"   ✗ 기본 프로필 디렉토리 없음: {default_profile}")

        print()

        # 4. 구 경로 확인
        print("4. 구 프로필 경로 확인 (마이그레이션 전)")
        old_profile = project_root / "browser_data" / "browser_profile"

        if old_profile.exists():
            file_count = sum(1 for _ in old_profile.rglob('*') if _.is_file())
            print(f"   ⚠ 구 프로필이 아직 존재합니다: {old_profile}")
            print(f"     파일 수: {file_count}개")
            print(f"     → 정상 작동 확인 후 삭제하세요")
        else:
            print(f"   ✓ 구 프로필 없음 (정리 완료)")

        print()
        print("=" * 60)
        print("확인 완료!")
        print("=" * 60)
        print()

        # 요약
        if default_profile.exists():
            print("✓ 새 프로필 구조가 올바르게 설정되었습니다!")
            print(f"  브라우저는 다음 경로의 프로필을 사용합니다:")
            print(f"  {default_profile}")
        else:
            print("⚠ 새 프로필 디렉토리가 없습니다!")
            print(f"  마이그레이션 스크립트를 실행하세요:")
            print(f"  python scripts/migrate_browser_profiles.py")

    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    check_profile_configuration()
