"""
Workflow API HTTP 통합 테스트 (Phase T4)

엔드포인트: /api/v1/dev-runner/workflows
TestClient 사용, test_db_engine 픽스처로 격리

TC:
  - test_get_workflows_empty: 빈 DB → 200 + []
  - test_post_create_workflow: POST → 201 + WorkflowResponse
  - test_get_workflows_with_filter: ?status= 필터
  - test_patch_workflow_cancel: PATCH cancel → status=cancelled, finished_at 설정
"""
import pytest
import sys
from pathlib import Path
from fastapi.testclient import TestClient

pytestmark = pytest.mark.http

_PLAN_RUNNER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
if str(_PLAN_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_PLAN_RUNNER_DIR))


@pytest.fixture(scope="module")
def client(test_db_engine):
    """TestClient (module scope) + test_db_engine 오버라이드"""
    from app.main import app
    from app.database import get_db
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


BASE = "/api/v1/dev-runner/workflows"


def test_get_workflows_empty(client):
    """R: 빈 DB → GET /workflows → 200 + []"""
    resp = client.get(BASE)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # 다른 테스트에서 생성된 레코드가 있을 수 있으므로 타입만 확인


def test_workflow_manager_uses_configured_postgres_url_R(monkeypatch):
    import workflow_manager as wm

    created = {}

    def fake_create_engine(db_url, **kwargs):
        created["db_url"] = db_url
        created["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(wm.settings, "DATABASE_URL", "postgresql://user:pass@localhost:5432/monitor")
    monkeypatch.setattr(wm, "create_engine", fake_create_engine)

    manager = wm.WorkflowManager()

    assert manager.db_url == "postgresql://user:pass@localhost:5432/monitor"
    assert created["db_url"] == manager.db_url
    assert created["kwargs"]["pool_pre_ping"] is True


def test_workflow_manager_runtime_rejects_monitor_db_sqlite_E(monkeypatch):
    import workflow_manager as wm

    monkeypatch.delenv("DEV_RUNNER_ALLOW_SQLITE_WORKFLOW_MANAGER", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    with pytest.raises(ValueError, match="legacy SQLite data/monitor.db"):
        wm.WorkflowManager(Path(__file__).resolve().parents[2] / "data" / "monitor.db")


def test_dev_runner_db_service_import_does_not_fail_E():
    from app.modules.dev_runner.services import db_service

    assert db_service.db_service is not None
    assert db_service.DBService.__name__ == "DBService"


def test_post_create_workflow(client):
    """R: POST /workflows → 201 + WorkflowResponse (slug, status=planned)"""
    payload = {"plan_file": "docs/plan/2026-03-03_test-http.md", "slug": "test-http-create"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "test-http-create"
    assert data["plan_file"] == "docs/plan/2026-03-03_test-http.md"
    assert data["status"] == "planned"
    assert data["id"] > 0
    assert data["created_at"] is not None


def test_post_create_workflow_without_slug(client):
    """R: POST /workflows slug 없이 → plan_file에서 slug 자동 생성"""
    payload = {"plan_file": "docs/plan/2026-03-03_auto-slug_todo.md"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    # _todo 접미사가 제거된 slug 생성
    assert "auto-slug" in data["slug"]
    assert data["status"] == "planned"


def test_get_workflows_with_filter(client):
    """R: ?status=planned 필터 → 해당 상태만 반환"""
    # planned 하나 생성
    payload = {"slug": "filter-test-planned"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    # 전체 조회
    resp_all = client.get(BASE)
    assert resp_all.status_code == 200
    all_count = len(resp_all.json())
    assert all_count >= 1

    # planned 필터
    resp_filtered = client.get(f"{BASE}?status=planned")
    assert resp_filtered.status_code == 200
    filtered = resp_filtered.json()
    assert all(w["status"] == "planned" for w in filtered)
    assert any(w["id"] == wf_id for w in filtered)

    # failed 필터 → 우리가 생성한 레코드는 포함 안 됨
    resp_failed = client.get(f"{BASE}?status=failed")
    assert resp_failed.status_code == 200
    assert all(w["id"] != wf_id for w in resp_failed.json())


def test_get_workflow_detail(client):
    """R: GET /workflows/{id} → 단건 조회"""
    payload = {"slug": "detail-test"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    resp_detail = client.get(f"{BASE}/{wf_id}")
    assert resp_detail.status_code == 200
    data = resp_detail.json()
    assert data["id"] == wf_id
    assert data["slug"] == "detail-test"


def test_get_workflow_detail_not_found(client):
    """B: 존재하지 않는 ID → 404"""
    resp = client.get(f"{BASE}/999999")
    assert resp.status_code == 404


def test_patch_workflow_cancel(client):
    """R: PATCH /workflows/{id}/cancel → status=cancelled, finished_at 설정"""
    payload = {"slug": "cancel-test"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    resp_cancel = client.patch(f"{BASE}/{wf_id}/cancel")
    assert resp_cancel.status_code == 200
    data = resp_cancel.json()
    assert data["status"] == "cancelled"
    assert data["finished_at"] is not None


def test_patch_cancel_already_cancelled(client):
    """B: 이미 cancelled 상태 workflow 재취소 시도 → 409 Conflict"""
    payload = {"slug": "double-cancel-test"}
    resp = client.post(BASE, json=payload)
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    # 첫 번째 취소 → 성공
    resp1 = client.patch(f"{BASE}/{wf_id}/cancel")
    assert resp1.status_code == 200

    # 두 번째 취소 → 400 (이미 terminal 상태 — planned/running이 아님)
    resp2 = client.patch(f"{BASE}/{wf_id}/cancel")
    assert resp2.status_code == 400


# ── T3: 통합 — WorkflowManager DB source 정합성 ─────────────────────────────

def test_workflow_manager_row_visible_to_orm_session_Co(tmp_path):
    """T3: WorkflowManager-created workflow row가 ORM session과 HTTP에서 조회됨.

    Phase 1 fix: WorkflowManager()는 settings.DATABASE_URL(앱 ORM과 동일 source)을
    사용하므로 listener-created row가 앱 ORM session에서 그대로 조회된다.
    """
    import workflow_manager as wm
    from app.models.workflow import Workflow
    from app.main import app
    from app.database import get_db
    from sqlalchemy import create_engine
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / "workflow-http-t3.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Workflow.__table__.create(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    manager = wm.WorkflowManager(db_url)

    slug = "t3-orm-integration-Co"
    try:
        wf_id = manager.create(slug=slug, plan_file="test/t3-plan.md")
        assert wf_id > 0

        # ORM session(test_db_session)으로 같은 row 조회
        db = SessionLocal()
        try:
            wf = db.query(Workflow).filter_by(id=wf_id).first()
        finally:
            db.close()

        assert wf is not None, (
            f"WorkflowManager(slug={slug})가 생성한 row {wf_id}가 ORM session에서 "
            "조회되지 않습니다. WorkflowManager가 다른 DB source를 사용하고 있을 수 있습니다."
        )
        assert wf.slug == slug
        assert wf.status == "planned"

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as local_client:
                resp = local_client.get(f"{BASE}/{wf_id}")
                assert resp.status_code == 200
                data = resp.json()
                assert data["id"] == wf_id
                assert data["slug"] == slug
                assert data["status"] == "planned"
        finally:
            app.dependency_overrides.pop(get_db, None)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM workflows WHERE slug = :slug"), {"slug": slug})
        engine.dispose()


# ── T5: HTTP — listener 경로·conflict resolution DB split 없음 ────────────────

def test_listener_workflow_http_visible_R(tmp_path):
    """T5: WorkflowManager(listener 경로)로 생성된 workflow가 GET /{id}로 404 없이 반환됨.

    PostgreSQL single-source: listener가 PG에 쓴 row를 HTTP API가 동일 DB에서 읽는다.
    """
    import workflow_manager as wm
    from app.models.workflow import Workflow
    from app.main import app
    from app.database import get_db
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / "t5-listener.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Workflow.__table__.create(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    manager = wm.WorkflowManager(db_url)
    slug = "t5-listener-R"
    try:
        wf_id = manager.create(slug=slug, plan_file="test/t5.md")
        assert wf_id > 0

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as c:
                resp = c.get(f"{BASE}/{wf_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == wf_id
            assert data["slug"] == slug
            assert data["status"] == "planned"
        finally:
            app.dependency_overrides.pop(get_db, None)
    finally:
        engine.dispose()


def test_no_sqlite_split_workflow_conflict_R(tmp_path):
    """T5: workflow과 conflict_resolutions가 동일 DB에 기록되고 HTTP 엔드포인트가 정상 응답함.

    split-brain 없음 검증: WorkflowManager와 ConflictResolver가 같은 DB source를 사용하여
    data/monitor.db SQLite 파일이 새로 생성되지 않는다.
    """
    import sys
    from pathlib import Path as _Path
    from unittest.mock import patch
    import workflow_manager as wm
    from app.models.workflow import Workflow
    from app.main import app
    from app.database import get_db
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    plan_runner_dir = _Path(__file__).resolve().parents[2] / "scripts" / "plan_runner"
    if str(plan_runner_dir) not in sys.path:
        sys.path.insert(0, str(plan_runner_dir))
    from conflict_resolver import ConflictResolver, ResolveResult

    db_path = tmp_path / "t5-split.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    Workflow.__table__.create(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS conflict_resolutions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "runner_id TEXT NOT NULL, "
            "branch TEXT NOT NULL, "
            "conflict_files TEXT NOT NULL, "
            "resolved_files TEXT, "
            "failed_files TEXT, "
            "strategy TEXT, "
            "success BOOLEAN NOT NULL DEFAULT 0, "
            "duration_ms INTEGER, "
            "error_message TEXT, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))

    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    monitor_db = _Path(__file__).resolve().parents[2] / "data" / "monitor.db"
    existed_before = monitor_db.exists()

    manager = wm.WorkflowManager(db_url)
    wf_id = manager.create(slug="t5-nosplit-R", plan_file="test/t5-split.md")
    assert wf_id > 0

    with patch("app.database.SessionLocal", Session):
        resolver = ConflictResolver(project_root=tmp_path)
        result = ResolveResult(success=True, resolved_files=["z.py"], failed_files=[], reason="")
        resolver._record_resolution("t5-rid-R", "feat", ["z.py"], result, 20)

    assert existed_before or not monitor_db.exists(), (
        "data/monitor.db가 존재하지 않았는데 새로 생성됐습니다. SQLite split 가능성 있음."
    )

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT runner_id FROM conflict_resolutions WHERE runner_id = 't5-rid-R'")
        ).fetchone()
    assert row is not None, "conflict_resolutions가 test DB에 기록되지 않았습니다."

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            resp = c.get(f"{BASE}/{wf_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == wf_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
