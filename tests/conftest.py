"""
pytest 설정 및 공통 픽스처

Windows에서 한글 출력 시 인코딩 문제 해결을 위한 설정 포함
테스트 DB 자동 생성 및 마이그레이션 적용 포함
"""

import sys
import os
import re
import sqlite3
import shutil
import io

# Windows에서 UTF-8 인코딩 강제 설정 (가장 먼저 실행)
if sys.platform == 'win32':
    # 환경 변수 설정 (다른 프로세스에도 영향)
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'

    # stdout/stderr를 UTF-8로 설정
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')


import pytest
import redis


from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 테스트 DB 경로 (TEST_DB_DIR 환경변수로 워크트리 격리 지원)
TEST_DB_DIR = Path(os.environ.get("TEST_DB_DIR", str(PROJECT_ROOT / "data")))
TEST_DB_PATH = TEST_DB_DIR / "test_monitor.db"
MIGRATIONS_DIR = PROJECT_ROOT / "app" / "migrations"


def get_migration_number(filename: str) -> int:
    """마이그레이션 파일 번호 추출 (예: 001_xxx.sql -> 1)"""
    match = re.match(r'^(\d+)', filename)
    return int(match.group(1)) if match else 999


def apply_migrations(db_path: Path) -> None:
    """마이그레이션 파일들을 순서대로 적용"""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 마이그레이션 파일 정렬 (번호순)
    migration_files = sorted(
        MIGRATIONS_DIR.glob("*.sql"),
        key=lambda f: (get_migration_number(f.name), f.name)
    )

    for sql_file in migration_files:
        try:
            sql_content = sql_file.read_text(encoding='utf-8')
            # 여러 문장으로 분리하여 실행
            statements = [s.strip() for s in sql_content.split(';') if s.strip()]
            for stmt in statements:
                try:
                    cursor.execute(stmt)
                except sqlite3.OperationalError as e:
                    # 이미 존재하는 테이블/컬럼 등은 무시
                    if "already exists" in str(e) or "duplicate column" in str(e).lower():
                        pass
                    else:
                        # 다른 에러도 무시 (테스트 DB이므로)
                        pass
        except Exception as e:
            # 파일 읽기 실패 등은 무시
            pass

    conn.commit()
    conn.close()


RUNNER_KEY_PREFIX = "plan-runner:runners"
ACTIVE_RUNNERS_KEY = "plan-runner:active_runners"
RECENT_RUNNERS_KEY = "plan-runner:recent_runners"


@pytest.fixture(autouse=True)
def redis_runner_cleanup():
    """테스트 전/후 Redis runner 키 자동 정리 fixture.

    테스트 시작 전 현재 ACTIVE_RUNNERS_KEY, RECENT_RUNNERS_KEY, RUNNER_KEY_PREFIX:* 키의
    스냅샷을 찍고, 테스트 후 새로 추가된 키만 삭제한다. 운영 runner는 보호된다.

    Redis 연결 실패 시 조용히 스킵(테스트 환경에 Redis가 없을 수 있음).
    """
    try:
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception:
        yield
        return

    def _scan_runner_keys():
        keys = set()
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor, match=f"{RUNNER_KEY_PREFIX}:*", count=100)
            keys.update(batch)
            if cursor == 0:
                break
        return keys

    # 테스트 시작 전 스냅샷
    before_runner_keys = _scan_runner_keys()
    before_active = r.smembers(ACTIVE_RUNNERS_KEY) or set()
    before_recent = r.zrange(RECENT_RUNNERS_KEY, 0, -1)
    before_recent_set = set(before_recent)

    yield

    # 테스트 후 새로 추가된 키 정리
    try:
        after_runner_keys = _scan_runner_keys()
        new_runner_keys = after_runner_keys - before_runner_keys
        if new_runner_keys:
            r.delete(*new_runner_keys)

        after_active = r.smembers(ACTIVE_RUNNERS_KEY) or set()
        new_active = after_active - before_active
        if new_active:
            r.srem(ACTIVE_RUNNERS_KEY, *new_active)

        after_recent = set(r.zrange(RECENT_RUNNERS_KEY, 0, -1))
        new_recent = after_recent - before_recent_set
        if new_recent:
            r.zrem(RECENT_RUNNERS_KEY, *new_recent)
    except Exception:
        pass  # cleanup 실패는 조용히 무시 (테스트 결과에 영향 주지 않음)


def _make_guarded_start_dev_runner(original):
    """start_dev_runner를 wrapping하여 test_source 누락 및 visible trigger를 즉시 실패시키는 guard를 반환한다."""
    async def _patched(request, *args, **kwargs):
        if not getattr(request, "test_source", None):
            pytest.fail(
                f"start_dev_runner() 호출 시 test_source 필수.\n"
                f"  request={request}\n"
                f"  RunRequest(plan_file=..., test_source='<tc_name>') 형태로 전달하세요."
            )
        trigger = getattr(request, "trigger", None)
        if trigger in ("user", "user:all"):
            pytest.fail(
                f"start_dev_runner() 호출 시 trigger='user' 또는 'user:all' 사용 금지.\n"
                f"  request={request}\n"
                f"  테스트에서 visible trigger 사용은 프론트엔드에 테스트 러너를 노출시킵니다.\n"
                f"  test_source를 설정하면 trigger가 자동으로 tc:{{test_source}}로 설정됩니다."
            )
        import os as _os
        _redis_db = _os.environ.get("PLAN_RUNNER_REDIS_DB", "0")
        if _redis_db == "0":
            pytest.fail(
                f"start_dev_runner() 호출 시 production Redis(db=0) 사용 금지.\n"
                f"  현재 PLAN_RUNNER_REDIS_DB={_redis_db!r} (기본값=production)\n"
                f"  tests/dev_runner/conftest_e2e.py의 isolated_redis fixture를 사용하세요.\n"
                f"  isolated_redis는 executor_service를 db=15로 재연결합니다."
            )
        return await original(request, *args, **kwargs)
    return _patched


@pytest.fixture(autouse=True)
def force_test_source_on_start_dev_runner():
    """전체 테스트에서 start_dev_runner 호출 시 test_source 누락 및 visible trigger를 즉시 실패시킨다.

    - test_source가 없으면 trigger="api" → visible=True → 프론트엔드에 테스트 러너가 노출된다.
    - trigger="user" 또는 "user:all" 직접 전달 시에도 guard가 차단한다.
    - 싱글톤 executor_service 뿐 아니라, 새로 생성된 ExecutorService() 인스턴스에도 자동 적용된다.
    - 이 guard는 tests/ 루트에 위치하여 모든 하위 디렉토리에 적용된다.
    """
    try:
        from app.modules.dev_runner.services import executor_service as es_module
        from app.modules.dev_runner.services.executor_service import ExecutorService, executor_service
    except Exception:
        yield
        return

    # 싱글톤 인스턴스 guard
    original_singleton = executor_service.start_dev_runner

    # 새 인스턴스 guard: __init__ 후 start_dev_runner를 자동으로 wrap
    original_init = ExecutorService.__init__

    def _patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # fakeredis 감지: production Redis가 아니면 guard 불필요
        # __init__ 완료 후 self.redis_client 타입 확인 → FakeRedis이면 guard wrapping 스킵
        try:
            import fakeredis as _fakeredis
            if isinstance(self.redis_client, _fakeredis.FakeRedis):
                return  # fakeredis 주입 확인 → production Redis 미사용, guard 불필요
        except ImportError:
            pass
        original_method = self.start_dev_runner
        # bound method를 guard로 교체
        guarded = _make_guarded_start_dev_runner(original_method)
        self.start_dev_runner = guarded

    with patch.object(executor_service, "start_dev_runner", side_effect=_make_guarded_start_dev_runner(original_singleton)), \
         patch.object(ExecutorService, "__init__", _patched_init):
        yield


@pytest.fixture()
def block_trigger_user_direct_write():
    """fakeredis에서 trigger='user' 직접 기록 차단 fixture (비autouse — 명시 사용 전용).

    단위 테스트에서 trigger='user'를 fakeredis에 직접 기록하는 코드를 탐지한다.
    autouse 대신 명시적으로 사용하여 격리 guard 자체를 검증하는 TC에서 활용한다.
    E2E 테스트는 allow_prod_redis 마커로 실서버 Redis를 사용하므로 이 fixture 불필요.
    """
    try:
        import fakeredis as _fakeredis
    except ImportError:
        yield
        return

    original_fake_set = _fakeredis.FakeRedis.set

    def _guarded_fake_set(self, name, value, *args, **kwargs):
        name_str = str(name) if name else ""
        value_str = str(value) if value else ""
        if name_str.endswith(":trigger") and value_str in ("user", "user:all"):
            pytest.fail(
                f"테스트에서 trigger='user' 또는 'user:all' Redis 직접 기록 금지.\n"
                f"  key={name!r}, value={value!r}\n"
                f"  tc:{{test_name}} 형태의 trigger를 사용하세요."
            )
        return original_fake_set(self, name, value, *args, **kwargs)

    with patch.object(_fakeredis.FakeRedis, "set", _guarded_fake_set):
        yield


@pytest.fixture(scope="session", autouse=True)
def _set_testing_env():
    """테스트 세션 동안 TESTING=1, TEST_DB_PATH 환경변수 설정

    - TESTING=1: lifespan 초기화 스킵으로 QueuePool 고갈 방지
    - TEST_DB_PATH: 서비스 레이어가 환경변수로 DB 경로를 읽을 경우 이중 방어
    """
    os.environ["TESTING"] = "1"
    os.environ["TEST_DB_PATH"] = str(TEST_DB_PATH)
    yield
    os.environ.pop("TESTING", None)
    os.environ.pop("TEST_DB_PATH", None)


@pytest.fixture(scope="session")
def test_db_engine():
    """
    마이그레이션이 적용된 테스트 DB 엔진 (세션 범위)

    DATABASE_URL 환경변수가 postgresql://로 시작하면 PG 엔진 사용,
    기본값은 SQLite 테스트 DB (기존 동작 유지).
    """
    from app.database import Base

    _url = os.environ.get("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
    _is_test_sqlite = _url.startswith("sqlite")

    if _is_test_sqlite:
        # TEST_DB_DIR 자동 생성 (worktree 환경에서 data 디렉토리 없을 수 있음)
        TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
        # 기존 테스트 DB 삭제
        if TEST_DB_PATH.exists():
            try:
                os.remove(TEST_DB_PATH)
            except PermissionError:
                pass

    from sqlalchemy import event as sa_event

    if _is_test_sqlite:
        engine = create_engine(_url, connect_args={"check_same_thread": False})

        @sa_event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    else:
        # PostgreSQL: check_same_thread/PRAGMA 불필요
        engine = create_engine(_url, pool_pre_ping=True)

    # 1. SQLAlchemy 모델로 기본 테이블 생성
    Base.metadata.create_all(bind=engine)

    # 2. 마이그레이션 적용 (SQLite 전용 — PG는 Base.metadata.create_all로 충분)
    if _is_test_sqlite:
        apply_migrations(TEST_DB_PATH)

    yield engine

    # 정리
    engine.dispose()
    if _is_test_sqlite:
        try:
            if TEST_DB_PATH.exists():
                os.remove(TEST_DB_PATH)
        except PermissionError:
            pass


@pytest.fixture(scope="function")
def test_db_session(test_db_engine):
    """
    테스트용 DB 세션 (함수 범위)

    각 테스트 함수마다 새로운 세션을 제공하고,
    테스트 종료 시 롤백하여 격리를 보장합니다.

    **SessionLocal 글로벌 패치 포함**:
    `app.database.SessionLocal` 및 `app.core.database.SessionLocal`을
    테스트 세션 팩토리로 교체하여, plan_service 등 내부 호출도
    테스트 DB를 사용하도록 보장합니다.
    """
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    session = Session()

    with patch("app.database.SessionLocal", Session), \
         patch("app.core.database.SessionLocal", Session):
        yield session

    session.rollback()
    session.close()


@pytest.fixture
def mock_external_request():
    """
    외부 요청을 시뮬레이션하는 fixture

    is_localhost_request가 False를 반환하도록 mock하여
    외부 IP에서의 요청처럼 동작하게 합니다.

    여러 모듈에서 import된 함수를 모두 mock해야 합니다.
    """
    from unittest.mock import patch

    with patch('app.core.auth.is_localhost_request', return_value=False), \
         patch('app.routes.auth.is_localhost_request', return_value=False):
        yield


# ============================================================
# 서비스 레이어 테스트용 Mock 픽스처
# ============================================================

@pytest.fixture
def mock_playwright_page():
    """Mock Playwright Page 객체"""
    from unittest.mock import AsyncMock, MagicMock

    page = AsyncMock()
    page.goto = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.content = AsyncMock(return_value="<html></html>")
    page.url = "https://example.com"
    page.is_closed = MagicMock(return_value=False)

    # locator 체이닝 지원
    locator = AsyncMock()
    locator.click = AsyncMock()
    locator.fill = AsyncMock()
    locator.inner_text = AsyncMock(return_value="텍스트")
    locator.text_content = AsyncMock(return_value="텍스트")
    locator.is_visible = AsyncMock(return_value=True)
    locator.count = AsyncMock(return_value=1)
    page.locator = MagicMock(return_value=locator)
    page.query_selector = AsyncMock(return_value=locator)
    page.query_selector_all = AsyncMock(return_value=[locator])

    return page


@pytest.fixture
def mock_playwright_browser():
    """Mock Playwright Browser 객체"""
    from unittest.mock import AsyncMock, MagicMock

    browser = AsyncMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.close = AsyncMock()

    # Context 생성 Mock
    context = AsyncMock()
    context.new_page = AsyncMock()
    context.close = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)

    return browser


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession"""
    from unittest.mock import AsyncMock, MagicMock

    response = AsyncMock()
    response.status = 200
    response.text = AsyncMock(return_value='{"ok": true}')
    response.json = AsyncMock(return_value={"ok": True})

    session = MagicMock()
    session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=response)))
    session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=response)))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    return session


@pytest.fixture
def mock_telegram_settings():
    """텔레그램 설정 Mock"""
    return {
        "bot_token": "test_bot_token",
        "chat_id": "test_chat_id"
    }
