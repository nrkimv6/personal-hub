"""T3: LLMWorker PG 연결 오류 traceback flood 재현 통합 TC.

근본 원인 재현:
- LLMWorker DB save 경로에서 psycopg2.OperationalError 발생 시
  수정 전: exc_info=True → traceback flood
  수정 후: warning 1회만 기록 (guard 적용)

mock은 외부 DB 드라이버(psycopg2)만 허용.
로거/핸들러는 실물 logging 모듈 사용.
"""
import logging
import pytest
import psycopg2
import sqlalchemy.exc
from unittest.mock import MagicMock

from app.modules.claude_worker.worker.worker import (
    save_instagram_result,
    save_writing_result,
    save_topic_extract_result,
)


class TracebackCapture(logging.Handler):
    """exc_info가 있는 로그 레코드를 수집하는 실물 핸들러."""

    def __init__(self):
        super().__init__()
        self.traceback_records = []
        self.warning_records = []

    def emit(self, record):
        if record.exc_info:
            self.traceback_records.append(record)
        if record.levelno == logging.WARNING and "PG connection error" in record.getMessage():
            self.warning_records.append(record)


@pytest.fixture
def traceback_capture():
    handler = TracebackCapture()
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    yield handler
    root_logger.removeHandler(handler)


def test_llm_worker_save_result_pg_connection_operational_error_reproduction(traceback_capture):
    """재현: save_instagram_result DB save 경로에서 psycopg2.OperationalError → guard 후 warning만."""
    db = MagicMock()
    post_mock = MagicMock()
    post_mock.images = []
    db.query.return_value.filter.return_value.first.return_value = post_mock
    db.flush.side_effect = psycopg2.OperationalError("could not connect to server")

    result = save_instagram_result(db, post_id=1, llm_result={"tag": "이벤트"})

    assert result is False
    assert len(traceback_capture.warning_records) == 1, "PG 연결 오류 시 warning 1회 필수"
    assert len(traceback_capture.traceback_records) == 0, "traceback flood 없어야 함 (guard 적용)"


def test_llm_worker_save_result_sqlalchemy_operational_error_reproduction(traceback_capture):
    """재현: save_writing_result에서 sqlalchemy OperationalError(orig=psycopg2) → guard 후 warning만."""
    orig = psycopg2.OperationalError("could not connect to server")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()
    db.commit.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, orig)

    req = MagicMock()
    req.id = 1
    req.caller_id = "1"
    req.writing_metadata = None
    req.writing_batch_id = None

    result = save_writing_result(db, req, {"task_type": "refine", "raw_response": "content"})

    assert result is False
    assert len(traceback_capture.warning_records) == 1, "PG 연결 오류 시 warning 1회 필수"
    assert len(traceback_capture.traceback_records) == 0, "traceback flood 없어야 함"


def test_llm_worker_multiple_save_paths_pg_error_no_flood(traceback_capture):
    """재현: 여러 save 경로 연속 PG 오류 → 각 1회씩 warning, traceback 없음."""
    pg_err = psycopg2.OperationalError("could not connect to server")

    db1 = MagicMock()
    post_mock = MagicMock()
    post_mock.images = []
    db1.query.return_value.filter.return_value.first.return_value = post_mock
    db1.flush.side_effect = pg_err

    db2 = MagicMock()
    db2.query.return_value.filter.return_value.first.return_value = MagicMock()
    db2.commit.side_effect = pg_err

    req = MagicMock()
    req.id = 2
    req.caller_id = "2"
    req.writing_metadata = None
    req.writing_batch_id = None

    save_instagram_result(db1, post_id=1, llm_result={"tag": "이벤트"})
    save_writing_result(db2, req, {"task_type": "refine", "raw_response": "x"})

    assert len(traceback_capture.warning_records) == 2, "PG 오류 2건 → warning 2회"
    assert len(traceback_capture.traceback_records) == 0, "traceback flood 없어야 함"
