# 브라우저 프로필 마이그레이션 가이드

## 개요

기존 브라우저 프로필 구조를 새로운 다중 프로필 지원 구조로 마이그레이션하는 방법을 설명합니다.

## 변경 사항

### 이전 구조
```
browser_data/
  └── browser_profile/     # 단일 프로필
```

### 새로운 구조
```
data/
  └── browser_profiles/
      ├── default/         # 기본 프로필
      ├── account_1/       # 계정 1 프로필
      └── account_2/       # 계정 2 프로필
```

## 마이그레이션 단계

### 1. 프로필 복사

브라우저 프로필을 새 위치로 복사합니다:

```bash
python scripts/migrate_browser_profiles.py
```

**주의사항:**
- 브라우저가 실행 중이면 일부 파일이 잠겨있어 건너뛰어질 수 있습니다
- 브라우저를 완전히 종료한 후 실행하면 모든 파일을 복사할 수 있습니다
- 기존 프로필은 삭제되지 않고 보존됩니다 (안전)

### 2. 설정 확인

프로필이 제대로 복사되었는지 확인:

```bash
python scripts/check_profile_config.py
```

예상 출력:
```
✓ 새 프로필 구조가 올바르게 설정되었습니다!
  브라우저는 다음 경로의 프로필을 사용합니다:
  D:\work\project\tools\monitor-page\data\browser_profiles\default
```

### 3. 브라우저 작동 확인

시스템을 실행하여 브라우저가 새 프로필을 사용하는지 확인:

```bash
# API 서버 시작
python app/main.py

# 또는 워커 직접 실행
python app/worker.py
```

브라우저가 정상적으로 열리고 기존 로그인 정보가 유지되는지 확인하세요.

### 4. 구 프로필 정리 (선택사항)

모든 것이 정상 작동하면 기존 프로필을 삭제할 수 있습니다:

```bash
# Windows
rmdir /s "browser_data\browser_profile"

# Linux/Mac
rm -rf browser_data/browser_profile
```

**주의:** 삭제 전에 반드시 정상 작동을 확인하세요!

## 설정 파일 변경 사항

### config.py

다음 설정이 추가되었습니다:

```python
# 데이터 디렉토리 설정
DATA_DIR: str = "./data"

# 다중 프로필 설정
BROWSER_PROFILES_DIR: str = "browser_profiles"
DEFAULT_PROFILE_NAME: str = "default"
```

### browser_service.py

- `get_or_create_context(service_account_id)`: 계정별 브라우저 컨텍스트 관리
- `_create_browser_context(service_account_id)`: 프로필 경로를 DB에서 자동으로 읽어옴

## 다중 프로필 사용 방법

### 1. 새 계정 추가

API를 통해 새 계정을 생성하면 자동으로 프로필 디렉토리가 생성됩니다:

```bash
POST /api/accounts
{
  "name": "서브계정",
  "profile_dir": "account_sub",
  "email": "sub@naver.com"
}
```

### 2. 계정별 모니터링

BizItem을 생성할 때 `service_account_id`를 지정하면 해당 계정의 브라우저 프로필을 사용합니다:

```bash
POST /api/biz-items
{
  "business_id": 1,
  "service_account_id": 2,  # 서브계정 사용
  "naver_booking_url": "https://..."
}
```

## 트러블슈팅

### 프로필 복사 실패

**증상:** 일부 파일이 복사되지 않음

**해결:**
1. 브라우저를 완전히 종료
2. 다시 마이그레이션 스크립트 실행

### 브라우저가 새 프로필을 사용하지 않음

**증상:** 로그인 정보가 사라짐

**해결:**
1. `check_profile_config.py` 실행하여 프로필 경로 확인
2. 로그에서 실제 사용 중인 프로필 경로 확인
3. 필요시 수동으로 프로필 파일 복사

### 파일 권한 오류

**증상:** `PermissionError` 발생

**해결:**
1. 관리자 권한으로 실행
2. 브라우저 프로세스 완전히 종료 (`taskkill /f /im chrome.exe`)

## 참고

- 마이그레이션 스크립트는 여러 번 실행해도 안전합니다
- 기존 파일은 덮어쓰기 모드로 작동합니다
- 프로필 디렉토리는 자동으로 생성됩니다
