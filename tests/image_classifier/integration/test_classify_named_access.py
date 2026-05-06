import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


class _DummyTaskProgressManager:
    def __init__(self, db):
        self.db = db

    def start_task(self, *_args, **_kwargs):
        return 1

    def update_progress(self, *_args, **_kwargs):
        return None

    def finish_task(self, *_args, **_kwargs):
        return None

    def complete_task(self, *_args, **_kwargs):
        return None

    def fail_task(self, *_args, **_kwargs):
        return None

    def pause_task(self, *_args, **_kwargs):
        return None


class _DummyCostTracker:
    def __init__(self, db):
        self.db = db

    def record_usage(self, **_kwargs):
        return None


class _ImmediateLLMService:
    def __init__(self, db):
        self.db = db

    def enqueue(self, **kwargs):
        return SimpleNamespace(id=int(kwargs["caller_id"]))

    def get_request_by_id(self, request_id):
        return SimpleNamespace(
            status="completed",
            result=json.dumps({
                "category": "여행",
                "confidence": 0.91,
                "reasoning": f"reason-for-{request_id}",
            }),
            error_message=None,
        )


class _DummyMonitorSession:
    def close(self):
        return None


class _FakeIndexFlatIP:
    def __init__(self, dims):
        self.dims = dims
        self.embeddings = None

    def add(self, embeddings):
        self.embeddings = embeddings

    def search(self, embeddings, k):
        count = embeddings.shape[0]
        distances = np.zeros((count, k), dtype=np.float32)
        indices = np.full((count, k), -1, dtype=np.int64)

        for idx in range(count):
            distances[idx, 0] = 1.0
            indices[idx, 0] = idx

        if count >= 2 and k >= 2:
            distances[0, 1] = 0.99
            distances[1, 1] = 0.99
            indices[0, 1] = 1
            indices[1, 1] = 0

        return distances, indices


def _seed_categories_and_files(db, tmp_path, file_ids):
    db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, '여행', '여행')
    """))

    for file_id in file_ids:
        file_path = tmp_path / f"img{file_id}.jpg"
        file_path.touch()
        db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, :hash, 'pending')
        """), {
            "id": file_id,
            "path": str(file_path),
            "hash": f"hash-{file_id}",
        })

    db.commit()


def _patch_run_classification_runtime(monkeypatch, session_factory):
    import app.modules.image_classifier.database as ic_database
    import app.modules.image_classifier.workers.cost_tracker as cost_tracker_module
    import app.modules.image_classifier.workers.log_buffer as log_buffer_module
    import app.modules.image_classifier.workers.task_progress as task_progress_module
    from app.modules.image_classifier.routers import classify as classify_module
    from app.modules.claude_worker.services import llm_service as llm_service_module

    monkeypatch.setattr(ic_database, "SessionLocal", session_factory)
    monkeypatch.setattr(task_progress_module, "TaskProgressManager", _DummyTaskProgressManager)
    monkeypatch.setattr(log_buffer_module, "pipeline_logs", SimpleNamespace(add=lambda *args, **kwargs: None))
    monkeypatch.setattr(cost_tracker_module, "CostTracker", _DummyCostTracker)
    monkeypatch.setattr(llm_service_module, "LLMService", _ImmediateLLMService)
    monkeypatch.setattr(classify_module, "_get_monitor_db_session", lambda: _DummyMonitorSession())
    monkeypatch.setattr(classify_module, "_build_classify_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(classify_module, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(classify_module, "POLL_TIMEOUT_SECONDS", 1)

    return classify_module


@pytest.mark.asyncio
async def test_run_classification_phash_copy_reads_named_representative_fields(test_db, monkeypatch, tmp_path):
    classify_module = _patch_run_classification_runtime(
        monkeypatch,
        sessionmaker(bind=test_db.get_bind()),
    )
    _seed_categories_and_files(test_db, tmp_path, [1, 2, 3])

    test_db.execute(text("""
        INSERT INTO duplicate_groups (id, group_hash, member_count, status)
        VALUES (100, 'dup-group-100', 3, 'pending')
    """))
    test_db.execute(text("""
        INSERT INTO duplicate_members (group_id, file_id, quality_score) VALUES
        (100, 1, 0.99),
        (100, 2, 0.75),
        (100, 3, 0.50)
    """))
    test_db.commit()

    files = [
        SimpleNamespace(id=1, file_path=str(tmp_path / "img1.jpg"), phash=None),
        SimpleNamespace(id=2, file_path=str(tmp_path / "img2.jpg"), phash=None),
        SimpleNamespace(id=3, file_path=str(tmp_path / "img3.jpg"), phash=None),
    ]
    classify_module.classification_status.clear()
    classify_module.classification_status.update({
        "running": True,
        "total": len(files),
        "processed": 0,
        "failed": 0,
        "current_file": None,
        "model": "claude_cli",
        "smart": False,
    })

    await classify_module.run_classification(
        files=files,
        model="claude_cli",
        batch_size=10,
        gap_minutes=0,
        max_workers=1,
    )

    rows = test_db.execute(text("""
        SELECT id, ai_category_id, ai_confidence, ai_reasoning, ai_model, status
        FROM file_classifications
        WHERE id IN (1, 2, 3)
        ORDER BY id
    """)).fetchall()

    assert [row[0] for row in rows] == [1, 2, 3]
    assert rows[0][1] == 1
    assert rows[1][1] == 1
    assert rows[2][1] == 1
    assert rows[1][2] == pytest.approx(0.91)
    assert rows[2][2] == pytest.approx(0.91)
    assert rows[1][3].startswith("[그룹 복사] reason-for-1")
    assert rows[2][3].startswith("[그룹 복사] reason-for-1")
    assert rows[1][4] == "claude_cli"
    assert rows[2][4] == "claude_cli"
    assert rows[1][5] == "ai_classified"
    assert rows[2][5] == "ai_classified"


@pytest.mark.asyncio
async def test_run_classification_clip_copy_reads_named_representative_fields(test_db, monkeypatch, tmp_path):
    classify_module = _patch_run_classification_runtime(
        monkeypatch,
        sessionmaker(bind=test_db.get_bind()),
    )
    _seed_categories_and_files(test_db, tmp_path, [10, 11])

    embedding = np.ones(512, dtype=np.float32).tobytes()
    test_db.execute(text("""
        INSERT INTO image_features (file_id, clip_embedding) VALUES
        (10, :embedding_a),
        (11, :embedding_b)
    """), {
        "embedding_a": embedding,
        "embedding_b": embedding,
    })
    test_db.commit()

    monkeypatch.setitem(
        sys.modules,
        "faiss",
        SimpleNamespace(
            IndexFlatIP=_FakeIndexFlatIP,
            normalize_L2=lambda _arr: None,
        ),
    )

    files = [
        SimpleNamespace(id=10, file_path=str(tmp_path / "img10.jpg"), phash=None),
        SimpleNamespace(id=11, file_path=str(tmp_path / "img11.jpg"), phash=None),
    ]
    classify_module.classification_status.clear()
    classify_module.classification_status.update({
        "running": True,
        "total": len(files),
        "processed": 0,
        "failed": 0,
        "current_file": None,
        "model": "claude_cli",
        "smart": True,
        "similarity_threshold": 0.85,
    })

    await classify_module.run_classification(
        files=files,
        model="claude_cli",
        batch_size=10,
        gap_minutes=0,
        max_workers=1,
    )

    rows = test_db.execute(text("""
        SELECT id, ai_category_id, ai_confidence, ai_reasoning, ai_model, status
        FROM file_classifications
        WHERE id IN (10, 11)
        ORDER BY id
    """)).fetchall()

    assert [row[0] for row in rows] == [10, 11]
    assert rows[0][1] == 1
    assert rows[1][1] == 1
    assert rows[1][2] == pytest.approx(0.91)
    assert rows[1][3].startswith("[CLIP 유사 복사] reason-for-10")
    assert rows[1][4] == "claude_cli"
    assert rows[1][5] == "ai_classified"
