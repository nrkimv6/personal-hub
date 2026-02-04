# 모바일 크롤링 서버

Galaxy S23 Ultra 상에서 실행되는 경량 FastAPI 서버로, 모바일 전용 페이지를 크롤링합니다.

## 시스템 요구사항

- Android 기기: Galaxy S23 Ultra
- Termux 앱
- Python 3.9 이상
- 헤디드 브라우저 (Chrome 또는 Chromium)

## 설치 방법 (Termux)

### 1. Termux 기본 환경 설정

```bash
# 패키지 업데이트
pkg update && pkg upgrade

# Python 설치
pkg install python

# pip 업그레이드
pip install --upgrade pip
```

### 2. 의존성 설치

```bash
cd mobile-server
pip install -r requirements.txt
```

### 3. 브라우저 설치 (Phase 1-2에서 결정)

Option 1: Playwright
```bash
pip install playwright
playwright install chromium
```

Option 2: Selenium (chromedriver 필요)
```bash
pip install selenium
# chromedriver 설치 방법은 별도 조사 필요
```

## 실행 방법

### 개발 모드

```bash
python main.py
```

서버가 http://0.0.0.0:8080 에서 실행됩니다.

### 백그라운드 실행 (Phase 8)

```bash
# TODO: Termux:Boot 설정 방법 추가
```

## API 엔드포인트

### GET /

루트 엔드포인트. 서버 정보를 반환합니다.

### GET /health

헬스체크 엔드포인트. 서버 및 브라우저 상태를 확인합니다.

```json
{
  "status": "healthy",
  "server_time": "2026-02-03T12:00:00",
  "browser_available": true,
  "uptime": "3600"
}
```

## 디렉토리 구조

```
mobile-server/
├── main.py              # FastAPI 앱 진입점
├── requirements.txt     # Python 의존성
├── README.md           # 이 파일
├── browser/            # 브라우저 매니저 모듈 (Phase 2)
├── crawlers/           # 크롤링 엔진 (Phase 5)
└── utils/              # 유틸리티 함수
```

## 개발 단계

- [x] Phase 1-3: 프로젝트 초기 구조 생성
- [ ] Phase 1-4: 헬스체크 API 구현
- [ ] Phase 2: Raw HTML 수집 API
- [ ] Phase 5: 구조화 크롤링 기능

## 문제 해결

### Termux에서 Python 패키지 설치 실패

일부 패키지는 컴파일이 필요할 수 있습니다:

```bash
pkg install clang
pkg install python-dev
```

### 브라우저 실행 실패

권한 문제 또는 메모리 부족일 수 있습니다. Phase 1-2 조사 단계에서 해결 방법을 확정합니다.

## 참고 문서

- 상위 PRD: `/docs/2026-02-03-mobile-monitoring-crawler.md`
- Termux Wiki: https://wiki.termux.com
