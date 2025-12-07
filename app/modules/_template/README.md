# 모듈 템플릿

새 모듈을 추가할 때 이 템플릿을 사용하세요.

## 사용 방법

1. 이 디렉토리를 복사하여 새 모듈 디렉토리 생성
2. `__init__.py.template`을 `__init__.py`로 이름 변경
3. 플레이스홀더를 실제 값으로 교체:
   - `{MODULE_CLASS_NAME}`: 모듈 클래스 이름 (예: `CoupangTravelModule`)
   - `{MODULE_DISPLAY_NAME}`: 표시 이름 (예: `쿠팡 트래블`)
   - `{MODULE_DESCRIPTION}`: 모듈 설명
   - `{module_name}`: 모듈 이름 (예: `coupang_travel`)
   - `{api_prefix}`: API 경로 prefix (예: `coupang`)

## 모듈 구조

```
new_module/
├── __init__.py          # 모듈 정의
├── README.md            # 모듈 문서
├── routes/              # API 라우트
│   └── __init__.py
├── services/            # 서비스 로직
│   └── __init__.py
├── models.py            # DB 모델
└── schemas.py           # Pydantic 스키마
```
