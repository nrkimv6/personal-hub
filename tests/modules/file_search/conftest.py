"""
파일 검색 모듈 공통 테스트 픽스처

파일 검색 모듈은 DB가 없으므로 최소 앱(file_search 라우터만 포함)으로 테스트합니다.
"""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.file_search.routes import router as file_search_router


@pytest.fixture
def test_app():
    """파일 검색 라우터만 포함한 최소 FastAPI 앱."""
    app = FastAPI()
    app.include_router(file_search_router)
    return app


@pytest.fixture
def client(test_app):
    """파일 검색용 TestClient."""
    return TestClient(test_app)


# ── Everything JSON 응답 픽스처 ──────────────────────────────────────────

@pytest.fixture
def everything_json_single():
    """Everything HTTP API 응답 — 결과 1건"""
    return {
        "totalResults": 1,
        "results": [
            {
                "name": "routes.py",
                "path": "D:\\work\\project\\app",
                "size": 2048,
                "date_modified": "2026-02-20T10:00:00",
            }
        ],
    }


@pytest.fixture
def everything_json_multi():
    """Everything HTTP API 응답 — 결과 3건"""
    return {
        "totalResults": 3,
        "results": [
            {"name": "search.py",  "path": "D:\\work\\project\\app", "size": 1024, "date_modified": "2026-02-20"},
            {"name": "models.py",  "path": "D:\\work\\project\\app", "size": 512,  "date_modified": "2026-02-19"},
            {"name": "schemas.py", "path": "D:\\work\\project\\app", "size": 768,  "date_modified": "2026-02-18"},
        ],
    }


@pytest.fixture
def everything_json_empty():
    """Everything HTTP API 응답 — 결과 없음"""
    return {"totalResults": 0, "results": []}


# ── ripgrep JSON 출력 픽스처 ─────────────────────────────────────────────

def _rg_match_line(file_path: str, line_number: int, text: str, start: int = 0, end: int = 4) -> str:
    """rg --json match 라인 생성 헬퍼."""
    return json.dumps({
        "type": "match",
        "data": {
            "path": {"text": file_path},
            "line_number": line_number,
            "lines": {"text": text + "\n"},
            "submatches": [{"start": start, "end": end, "match": {"text": text[start:end]}}],
        },
    })


def _rg_context_line(file_path: str, line_number: int, text: str) -> str:
    """rg --json context 라인 생성 헬퍼."""
    return json.dumps({
        "type": "context",
        "data": {
            "path": {"text": file_path},
            "line_number": line_number,
            "lines": {"text": text + "\n"},
            "submatches": [],
        },
    })


@pytest.fixture
def rg_stdout_single():
    """ripgrep JSON 출력 — 파일 1개, 매칭 1건"""
    fp = "/home/user/project/app/search.py"
    lines = [
        _rg_context_line(fp, 9,  "# context before"),
        _rg_context_line(fp, 10, "# context before 2"),
        _rg_match_line(fp, 11, "def search_files(query):", start=4, end=17),
        _rg_context_line(fp, 12, "    pass"),
        _rg_context_line(fp, 13, "    # context after"),
    ]
    return "\n".join(lines)


@pytest.fixture
def rg_stdout_multi_file():
    """ripgrep JSON 출력 — 파일 2개"""
    fp1 = "/home/user/project/app/a.py"
    fp2 = "/home/user/project/app/b.py"
    lines = [
        _rg_match_line(fp1, 5,  "def foo(): pass", start=4, end=7),
        _rg_match_line(fp2, 10, "def bar(): pass", start=4, end=7),
    ]
    return "\n".join(lines)


@pytest.fixture
def rg_stdout_empty():
    """ripgrep JSON 출력 — 결과 없음"""
    return ""
