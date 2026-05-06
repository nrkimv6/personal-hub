"""
Integration Test 전용 pytest 설정

테스트 서버를 자동으로 시작/종료하는 fixture 제공.

INTEGRATION_SERVER_URL 환경변수가 설정되면 이미 실행 중인 서버를 사용하고
새 서버를 시작하지 않는다 (포트 충돌 방지).
예: INTEGRATION_SERVER_URL=http://localhost:8001 pytest tests/integration/
"""

import pytest
import subprocess
import time
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# requests는 optional dependency
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import psycopg2
    from psycopg2 import sql
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_DB_DIR = Path(os.environ.get("TEST_DB_DIR", str(PROJECT_ROOT / "data")))
TEST_DB_PATH = TEST_DB_DIR / "test_integration_monitor.db"
TEST_SERVER_PORT = int(os.environ.get("TEST_SERVER_PORT", "18001"))


@dataclass(frozen=True)
class IntegrationCleanupFailure:
    method: str
    path: str
    error: str


class IntegrationResourceCleanup:
    """Best-effort API cleanup for resources created by HTTP integration tests."""

    def __init__(self, base_url: str, http_client=None, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or requests
        self.timeout = timeout
        self._business_ids: list[int] = []
        self._item_ids: list[int] = []

    def add_business(self, business_id: int | str | None) -> None:
        parsed_id = self._parse_id(business_id)
        if parsed_id is not None and parsed_id not in self._business_ids:
            self._business_ids.append(parsed_id)

    def add_item(self, item_id: int | str | None) -> None:
        parsed_id = self._parse_id(item_id)
        if parsed_id is not None and parsed_id not in self._item_ids:
            self._item_ids.append(parsed_id)

    def add_import_result(self, payload: dict) -> None:
        self.add_item(payload.get("item_id"))
        self.add_business(payload.get("business_id"))

    def cleanup(self) -> list[IntegrationCleanupFailure]:
        failures: list[IntegrationCleanupFailure] = []
        for item_id in reversed(self._item_ids):
            failures.extend(self._delete(f"/api/v1/items/{item_id}"))
        for business_id in reversed(self._business_ids):
            failures.extend(self._delete(f"/api/v1/businesses/{business_id}"))
        return failures

    def _delete(self, path: str) -> list[IntegrationCleanupFailure]:
        try:
            response = self.http_client.delete(
                f"{self.base_url}{path}",
                timeout=self.timeout,
            )
            if response.status_code in (204, 404):
                return []
            return [
                IntegrationCleanupFailure(
                    method="DELETE",
                    path=path,
                    error=f"status_code={response.status_code}",
                )
            ]
        except Exception as exc:
            return [
                IntegrationCleanupFailure(
                    method="DELETE",
                    path=path,
                    error=str(exc),
                )
            ]

    @staticmethod
    def _parse_id(value: int | str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def _replace_database_name(db_url: str, database_name: str) -> str:
    parsed = urlsplit(db_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))


def _parse_database_name(db_url: str) -> str:
    parsed = urlsplit(db_url)
    return parsed.path.lstrip("/")


def _parse_search_path(db_url: str) -> str | None:
    parsed = urlsplit(db_url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    for key, value in query_pairs:
        if key != "options":
            continue
        marker = "search_path="
        if marker in value:
            return value.split(marker, 1)[1].strip()
    return None


def _remove_search_path_option(db_url: str) -> str:
    parsed = urlsplit(db_url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_pairs = []
    for key, value in query_pairs:
        if key == "options" and "search_path=" in value:
            continue
        filtered_pairs.append((key, value))
    return urlunsplit(parsed._replace(query=urlencode(filtered_pairs)))


def _connect_postgres_target_db(target_db_url: str):
    if not HAS_PSYCOPG2:
        raise RuntimeError("PostgreSQL 테스트 스키마 초기화를 위해 psycopg2가 필요합니다")
    conn = psycopg2.connect(_remove_search_path_option(target_db_url))
    conn.autocommit = True
    return conn


def _prepare_postgres_test_database(db_url: str) -> None:
    target_db_name = _parse_database_name(db_url)
    if not target_db_name:
        raise RuntimeError(f"PostgreSQL DATABASE_URL에 DB 이름이 없습니다: {db_url}")

    schema_name = _parse_search_path(db_url)
    if schema_name and schema_name.startswith("test_"):
        conn = _connect_postgres_target_db(db_url)
        try:
            cur = conn.cursor()
            cur.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            cur.execute(
                sql.SQL("CREATE SCHEMA {}").format(
                    sql.Identifier(schema_name)
                )
            )
        finally:
            conn.close()
        return

    conn = _connect_postgres_target_db(db_url)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (target_db_name,),
        )
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(target_db_name)
                )
            )
    finally:
        conn.close()


@pytest.fixture(scope="session")
def integration_server():
    """
    Integration Test용 테스트 서버 자동 실행

    INTEGRATION_SERVER_URL 환경변수가 있으면 해당 서버를 사용하고
    새 서버를 시작하지 않는다 (포트 충돌 방지).
    없으면 포트 18001에서 신규 테스트 서버를 시작한다.
    """
    if not HAS_REQUESTS:
        pytest.skip("requests 모듈이 필요합니다: pip install requests")

    # INTEGRATION_SERVER_URL이 설정되면 이미 실행 중인 서버 사용
    live_url = os.environ.get("INTEGRATION_SERVER_URL")
    if live_url:
        try:
            resp = requests.get(f"{live_url}/api/v1/businesses", timeout=5)
            if resp.status_code == 200:
                yield live_url
                return
        except Exception:
            pass
        pytest.skip(f"INTEGRATION_SERVER_URL={live_url} 서버에 연결할 수 없습니다")
        return

    # 0. TEST_DB_DIR 자동 생성 (worktree 환경에서 data 디렉토리 없을 수 있음)
    TEST_DB_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 기존 테스트 DB 삭제 (깨끗한 상태로 시작)
    if TEST_DB_PATH.exists():
        os.remove(TEST_DB_PATH)

    # 2. 테스트 서버 실행 (별도 포트, 테스트 DB)
    env = os.environ.copy()
    # PostgreSQL 테스트 DB (환경변수로 오버라이드 가능)
    default_pg_url = (
        "postgresql://monitor_user:monitor_pass_2026@localhost:5432/monitor"
        "?options=-csearch_path%3Dtest_monitor"
    )
    test_db_url = os.environ.get("TEST_DATABASE_URL", default_pg_url)
    env["DATABASE_URL"] = test_db_url
    if test_db_url.startswith("postgresql://"):
        _prepare_postgres_test_database(test_db_url)
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    # Windows에서는 python.exe 사용
    python_exe = sys.executable

    proc = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "app.main:app", "--port", str(TEST_SERVER_PORT)],
        env=env,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 3. 서버 준비 대기 (health check)
    base_url = f"http://localhost:{TEST_SERVER_PORT}"
    max_wait = 15

    for i in range(max_wait):
        try:
            resp = requests.get(f"{base_url}/api/v1/businesses", timeout=1)
            if resp.status_code == 200:
                break
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    else:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"테스트 서버 시작 실패\n"
            f"stdout: {stdout.decode('utf-8', errors='replace')}\n"
            f"stderr: {stderr.decode('utf-8', errors='replace')}"
        )

    yield base_url

    # 4. 정리
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    if TEST_DB_PATH.exists():
        os.remove(TEST_DB_PATH)


@pytest.fixture
def integration_cleanup(integration_server):
    cleanup = IntegrationResourceCleanup(integration_server)
    yield cleanup
    failures = cleanup.cleanup()
    assert not failures, "integration cleanup failed:\n" + "\n".join(
        f"{failure.method} {failure.path}: {failure.error}"
        for failure in failures
    )
