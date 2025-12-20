# App 모듈 설치 가이드

> 기본 실행 방법은 프로젝트 루트의 `CLAUDE.md`를 참조하세요.

## 의존성 설치

```bash
# 기본 패키지
pip install fastapi uvicorn pydantic sqlalchemy

# 추가 패키지
pip install pytz psutil playwright aiohttp plyer beautifulsoup4

# Playwright 브라우저 설치
playwright install chromium
```

## 개별 실행 (개발용)

```bash
# API 서버만 실행 (프로젝트 루트에서)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 문제 해결

`ModuleNotFoundError: No module named 'XXX'` 오류 시:

```bash
pip install XXX
```
