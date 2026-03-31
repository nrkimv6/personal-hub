"""fakeredis 기반 dev_runner TC 공유 헬퍼 — pytest conftest는 직접 import 불가하여 별도 모듈로 추출"""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def mock_merge_queue_turn(repo_id: str):
    """fakeredis 기반 E2E TC에서 merge_queue 함수 mock 헬퍼.

    ⚠️ fakeredis는 Lua eval 미지원 — merge_queue.py의 acquire_merge_turn()이
    _ENQUEUE_LUA 스크립트를 eval()로 실행하므로 `unknown command 'eval'` 오류 발생.
    merge_queue 함수를 직접 호출하는 모든 TC는 반드시 이 context manager를 사용할 것.

    Usage:
        with mock_merge_queue_turn("my-repo"):
            # TC 코드 — acquire/release는 mock으로 대체됨
    """
    with patch("merge_queue.acquire_merge_turn", return_value=True), \
         patch("merge_queue.release_merge_turn", return_value=True), \
         patch("merge_queue._get_repo_id", return_value=repo_id):
        yield
