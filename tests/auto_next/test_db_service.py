"""DBService 단위 테스트 - RIGHT-BICEP 원칙 적용

대상 소스: app/modules/auto_next/services/db_service.py
Phase 2 of auto-next-test-enhancement plan
"""

import sqlite3
import pytest
from datetime import datetime, timedelta

from app.modules.auto_next.services.db_service import DBService


# ========== Fixtures ==========

def _create_test_db(db_path, rows=None):
    """테스트 DB 생성 헬퍼"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'plan_item',
            source_path TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            output_tokens INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_create_tokens INTEGER DEFAULT 0,
            error_message TEXT,
            model_used TEXT
        )
    """)
    if rows:
        for row in rows:
            conn.execute(
                """INSERT INTO tasks (id, type, source_path, text, priority, status,
                   created_at, started_at, finished_at,
                   input_tokens, output_tokens, cache_read_tokens, cache_create_tokens,
                   error_message, model_used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row
            )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def empty_db(tmp_path):
    """빈 테스트 DB"""
    return DBService(db_path=_create_test_db(tmp_path / "empty.db"))


@pytest.fixture
def populated_db(tmp_path):
    """데이터가 있는 테스트 DB"""
    now = datetime.now()
    rows = [
        ("t1", "plan_item", "plan_a.md", "Task A1", 0, "success",
         (now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=2)).isoformat(),
         (now - timedelta(hours=1, minutes=58)).isoformat(),
         100, 200, 50, 10, None, "claude-3"),
        ("t2", "plan_item", "plan_a.md", "Task A2", 1, "pending",
         (now - timedelta(hours=1)).isoformat(), None, None,
         0, 0, 0, 0, None, None),
        ("t3", "plan_item", "plan_b.md", "Task B1", 0, "failed",
         (now - timedelta(minutes=30)).isoformat(),
         (now - timedelta(minutes=30)).isoformat(),
         (now - timedelta(minutes=28)).isoformat(),
         50, 0, 0, 0, "Some error", "claude-3"),
        ("t4", "plan_item", "plan_a.md", "Task A3", 0, "skipped",
         (now - timedelta(minutes=10)).isoformat(),
         (now - timedelta(minutes=10)).isoformat(),
         (now - timedelta(minutes=9)).isoformat(),
         0, 0, 0, 0, None, None),
        ("t5", "plan_item", "plan_b.md", "Task B1", 0, "success",
         (now - timedelta(minutes=5)).isoformat(),
         (now - timedelta(minutes=5)).isoformat(),
         (now - timedelta(minutes=4)).isoformat(),
         80, 150, 30, 5, None, "claude-3"),
    ]
    return DBService(db_path=_create_test_db(tmp_path / "populated.db", rows))


# ========== get_tasks() ==========

class TestGetTasks:

    def test_empty_db_returns_empty(self, empty_db):
        """빈 DB → tasks=[], total=0"""
        result = empty_db.get_tasks()
        assert result.tasks == []
        assert result.total == 0

    def test_all_tasks_returned(self, populated_db):
        """전체 조회 시 모든 태스크 반환"""
        result = populated_db.get_tasks()
        assert result.total == 5
        assert len(result.tasks) == 5

    def test_source_path_filter(self, populated_db):
        """source_path 필터링"""
        result = populated_db.get_tasks(source_path="plan_a.md")
        assert result.total == 3
        assert all(t.source_path == "plan_a.md" for t in result.tasks)

    def test_status_filter(self, populated_db):
        """status 필터링"""
        result = populated_db.get_tasks(status="success")
        assert result.total == 2
        assert all(t.status == "success" for t in result.tasks)

    def test_combined_filter(self, populated_db):
        """status + source_path 복합 필터"""
        result = populated_db.get_tasks(status="success", source_path="plan_a.md")
        assert result.total == 1
        assert result.tasks[0].id == "t1"

    def test_limit_offset_pagination(self, populated_db):
        """limit/offset 페이지네이션"""
        page1 = populated_db.get_tasks(limit=2, offset=0)
        page2 = populated_db.get_tasks(limit=2, offset=2)

        assert len(page1.tasks) == 2
        assert len(page2.tasks) == 2
        assert page1.total == 5
        ids1 = {t.id for t in page1.tasks}
        ids2 = {t.id for t in page2.tasks}
        assert ids1.isdisjoint(ids2)

    def test_offset_beyond_total(self, populated_db):
        """offset > total → 빈 리스트"""
        result = populated_db.get_tasks(offset=100)
        assert result.tasks == []
        assert result.total == 5


# ========== get_stats() ==========

class TestGetStats:

    def test_empty_db_all_zero(self, empty_db):
        """빈 DB → 모든 값 0"""
        stats = empty_db.get_stats()
        assert stats.total == 0
        assert stats.pending == 0
        assert stats.completion_rate == 0.0
        assert stats.success_rate == 0.0
        assert stats.total_tokens == 0

    def test_completion_rate(self, populated_db):
        """completion_rate = completed / total"""
        stats = populated_db.get_stats()
        assert stats.completed == 4
        assert stats.completion_rate == pytest.approx(4 / 5)

    def test_success_rate(self, populated_db):
        """success_rate = success / completed"""
        stats = populated_db.get_stats()
        assert stats.success_rate == pytest.approx(2 / 4)

    def test_token_aggregation(self, populated_db):
        """토큰 합산 정확성"""
        stats = populated_db.get_stats()
        assert stats.total_input_tokens == 230   # 100+0+50+0+80
        assert stats.total_output_tokens == 350  # 200+0+0+0+150
        assert stats.total_cache_tokens == 95    # (50+10)+(0+0)+(0+0)+(0+0)+(30+5)
        assert stats.total_tokens == 230 + 350 + 95

    def test_status_counts(self, populated_db):
        """상태별 카운트"""
        stats = populated_db.get_stats()
        assert stats.success == 2
        assert stats.failed == 1
        assert stats.skipped == 1
        assert stats.pending == 1
        assert stats.running == 0

    def test_since_filter(self, populated_db):
        """since 파라미터 날짜 필터링"""
        since = (datetime.now() - timedelta(minutes=20)).isoformat()
        stats = populated_db.get_stats(since=since)
        assert stats.total == 2  # t4(10분전), t5(5분전)


# ========== delete 계열 ==========

class TestDelete:

    def test_delete_completed_tasks(self, populated_db):
        """완료 태스크(success/failed/skipped) 삭제"""
        count = populated_db.delete_completed_tasks()
        assert count == 4

        remaining = populated_db.get_tasks()
        assert remaining.total == 1
        assert remaining.tasks[0].status == "pending"

    def test_delete_completed_with_source_path(self, populated_db):
        """source_path 필터와 함께 완료 삭제"""
        count = populated_db.delete_completed_tasks(source_path="plan_a.md")
        assert count == 2  # t1(success), t4(skipped)

    def test_delete_task_nonexistent(self, populated_db):
        """존재하지 않는 ID → False"""
        assert populated_db.delete_task("nonexistent-id") is False

    def test_delete_task_existing(self, populated_db):
        """존재하는 ID → True"""
        assert populated_db.delete_task("t1") is True
        assert populated_db.get_task_by_id("t1") is None

    def test_delete_old_tasks(self, tmp_path):
        """hours 기준 삭제"""
        now = datetime.now()
        rows = [
            ("old1", "plan_item", "p.md", "Old task", 0, "success",
             (now - timedelta(hours=48)).isoformat(),
             (now - timedelta(hours=48)).isoformat(),
             (now - timedelta(hours=47)).isoformat(),
             0, 0, 0, 0, None, None),
            ("new1", "plan_item", "p.md", "New task", 0, "success",
             now.isoformat(), now.isoformat(),
             (now + timedelta(minutes=1)).isoformat(),
             0, 0, 0, 0, None, None),
        ]
        db = DBService(db_path=_create_test_db(tmp_path / "old.db", rows))
        count = db.delete_old_tasks(hours=24)
        assert count == 1
        assert db.get_task_by_id("new1") is not None


# ========== get_history() / find_duplicate_tasks() ==========

class TestHistoryAndDuplicates:

    def test_history_date_grouping(self, populated_db):
        """날짜별 그룹핑"""
        history = populated_db.get_history(days=30)
        assert len(history) >= 1
        total_count = sum(h.count for h in history)
        assert total_count == 4  # finished_at이 있는 것만 (t2 제외)

    def test_duplicate_tasks(self, populated_db):
        """중복 text 감지 (Task B1이 t3, t5에서 중복)"""
        dups = populated_db.find_duplicate_tasks(min_count=2)
        assert len(dups) == 1
        assert dups[0].text == "Task B1"
        assert dups[0].count == 2

    def test_no_duplicates(self, populated_db):
        """min_count=10 → 빈 결과"""
        dups = populated_db.find_duplicate_tasks(min_count=10)
        assert dups == []


# ========== get_task_by_id() ==========

class TestGetTaskById:

    def test_existing_task(self, populated_db):
        """존재하는 task 조회"""
        task = populated_db.get_task_by_id("t1")
        assert task is not None
        assert task.text == "Task A1"
        assert task.status == "success"

    def test_nonexistent_task(self, populated_db):
        """존재하지 않는 task → None"""
        assert populated_db.get_task_by_id("nonexistent") is None

    def test_duration_calculation(self, populated_db):
        """duration_seconds 계산"""
        task = populated_db.get_task_by_id("t1")
        assert task.duration_seconds is not None
        assert task.duration_seconds > 0

    def test_duration_none_when_not_finished(self, populated_db):
        """started_at/finished_at 없으면 duration=None"""
        task = populated_db.get_task_by_id("t2")
        assert task.duration_seconds is None
