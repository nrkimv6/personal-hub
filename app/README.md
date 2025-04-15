실행방법

# 설치 및 실행 방법

## 1. 가상 환경 생성 및 활성화
Python 3.9 이하 버전에서 실행하는 것이 좋습니다. Python 3.12는 FastAPI 및 Pydantic과 호환성 문제가 있을 수 있습니다.

```bash
# conda 환경 생성 (권장)
conda create -n monitor-env python=3.9 -y
conda activate monitor-env

# 또는 venv 사용
# python -m venv venv
# Windows: venv\Scripts\activate
# Linux/MacOS: source venv/bin/activate
```

## 2. 필요한 패키지 설치

```bash
# 기본 패키지 설치
pip install fastapi==0.95.2 uvicorn==0.22.0 pydantic==1.10.8

# 추가 필요한 패키지
pip install pytz sqlalchemy psutil playwright aiohttp plyer beautifulsoup4

# playwright 브라우저 설치
playwright install chromium
```

## 3. 서버 실행 방법

### 방법 1: 프로젝트 루트 디렉토리에서 실행
프로젝트 루트 디렉토리(monitor-page)에서 다음 명령어를 실행합니다:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 방법 2: app 디렉토리에서 실행
app 디렉토리로 이동하여 다음 명령어를 실행합니다:

```bash
cd app
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 4. 접속 방법

서버 실행 후 브라우저에서 다음 주소로 접속할 수 있습니다:
- API 메인 페이지: http://localhost:8000
- API 문서: http://localhost:8000/docs

## 5. 문제 해결 방법

다음과 같은 오류가 발생하면 필요한 패키지를 설치하세요:

```
ModuleNotFoundError: No module named 'XXX'
```

이 경우 다음 명령어로 해당 패키지를 설치합니다:

```bash
pip install XXX
```
