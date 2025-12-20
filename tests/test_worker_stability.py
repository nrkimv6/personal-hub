"""
워커 안정성 버그 수정 테스트

테스트 대상:
1. PROXY_ENABLED 설정 적용 (버그 1)
2. 워커 헬스 모니터링 개선 (버그 2)
3. Anonymous/탭 기반 태스크 카운트 분리 (버그 3)

RIGHT-BICEP 원칙:
- Right: 올바른 결과 반환
- Boundary: 경계 조건 테스트
- Inverse: 반대 조건 테스트
- Cross-check: 교차 검증
- Error: 에러 조건 테스트
- Performance: 성능 테스트 (해당시)
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock


class TestProxyEnabledSetting:
    """버그 1: PROXY_ENABLED 설정 테스트"""

    @pytest.mark.asyncio
    async def test_initialize_proxy_manager_disabled(self):
        """[Right] PROXY_ENABLED=False일 때 None 반환"""
        with patch("app.services.proxy_manager_factory.settings") as mock_settings:
            mock_settings.PROXY_ENABLED = False

            from app.services.proxy_manager_factory import initialize_proxy_manager

            result = await initialize_proxy_manager()

            assert result is None

    @pytest.mark.asyncio
    async def test_initialize_proxy_manager_enabled(self):
        """[Right] PROXY_ENABLED=True일 때 프록시 매니저 반환"""
        with patch("app.services.proxy_manager_factory.settings") as mock_settings, \
             patch("app.services.proxy_manager_factory.get_proxy_manager") as mock_get, \
             patch("app.services.proxy_manager_factory._proxy_manager_instance", None):

            mock_settings.PROXY_ENABLED = True
            mock_settings.PROXY_BACKEND = "file"
            mock_manager = MagicMock()
            mock_manager.is_available = True
            mock_get.return_value = mock_manager

            from app.services.proxy_manager_factory import initialize_proxy_manager

            result = await initialize_proxy_manager()

            assert result is not None
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_proxy_manager_logs_disabled_message(self):
        """[Right] PROXY_ENABLED=False일 때 로그 메시지 출력"""
        with patch("app.services.proxy_manager_factory.settings") as mock_settings, \
             patch("app.services.proxy_manager_factory.logger") as mock_logger:

            mock_settings.PROXY_ENABLED = False

            from app.services.proxy_manager_factory import initialize_proxy_manager

            await initialize_proxy_manager()

            mock_logger.info.assert_called_with("PROXY_ENABLED=False, 프록시 매니저 비활성화")


class TestTaskCountSeparation:
    """버그 3: Anonymous/탭 기반 태스크 카운트 분리 테스트"""

    def create_mock_queue_manager(self):
        """테스트용 MonitoringQueue Mock 생성"""
        mock = MagicMock()
        mock.monitoring_tasks = {}
        mock.anonymous_task_ids = set()
        mock.TOTAL_MAX_TABS = 5
        mock.MAX_CONCURRENT_ANONYMOUS = 10
        return mock

    def test_get_tab_based_task_count_only_anonymous(self):
        """[Right] Anonymous 태스크만 있을 때 탭 기반 카운트는 0"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        # Mock 설정
        mock_task1 = MagicMock()
        mock_task1.done.return_value = False
        mock_task2 = MagicMock()
        mock_task2.done.return_value = False

        # MonitoringQueue 인스턴스 생성 (Mock 주입)
        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.monitoring_tasks = {1: mock_task1, 2: mock_task2}
            manager.anonymous_task_ids = {1, 2}  # 모두 Anonymous

            result = manager._get_tab_based_task_count()

            assert result == 0

    def test_get_tab_based_task_count_only_tab_based(self):
        """[Right] 탭 기반 태스크만 있을 때 정확한 카운트"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        mock_task1 = MagicMock()
        mock_task1.done.return_value = False
        mock_task2 = MagicMock()
        mock_task2.done.return_value = False
        mock_task3 = MagicMock()
        mock_task3.done.return_value = False

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.monitoring_tasks = {1: mock_task1, 2: mock_task2, 3: mock_task3}
            manager.anonymous_task_ids = set()  # Anonymous 없음

            result = manager._get_tab_based_task_count()

            assert result == 3

    def test_get_tab_based_task_count_mixed(self):
        """[Right] Anonymous + 탭 기반 혼합 시 탭 기반만 카운트"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        mock_task1 = MagicMock()
        mock_task1.done.return_value = False
        mock_task2 = MagicMock()
        mock_task2.done.return_value = False
        mock_task3 = MagicMock()
        mock_task3.done.return_value = False
        mock_task4 = MagicMock()
        mock_task4.done.return_value = False

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.monitoring_tasks = {
                1: mock_task1,  # Anonymous
                2: mock_task2,  # Tab-based
                3: mock_task3,  # Anonymous
                4: mock_task4,  # Tab-based
            }
            manager.anonymous_task_ids = {1, 3}  # 1, 3만 Anonymous

            result = manager._get_tab_based_task_count()

            assert result == 2  # 2, 4만 카운트

    def test_get_tab_based_task_count_excludes_completed(self):
        """[Right] 완료된 태스크는 카운트에서 제외"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        mock_task1 = MagicMock()
        mock_task1.done.return_value = False  # 실행 중
        mock_task2 = MagicMock()
        mock_task2.done.return_value = True   # 완료됨

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.monitoring_tasks = {1: mock_task1, 2: mock_task2}
            manager.anonymous_task_ids = set()

            result = manager._get_tab_based_task_count()

            assert result == 1  # 완료된 태스크 제외

    def test_get_tab_based_task_count_boundary_empty(self):
        """[Boundary] 태스크가 없을 때 0 반환"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.monitoring_tasks = {}
            manager.anonymous_task_ids = set()

            result = manager._get_tab_based_task_count()

            assert result == 0


class TestCheckQueueAfterTaskCompletion:
    """_check_queue_after_task_completion 분리된 카운트 사용 테스트"""

    @pytest.mark.asyncio
    async def test_has_space_with_anonymous_full_tab_available(self):
        """[Right] Anonymous 가득 + 탭 여유 = 공간 있음"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.TOTAL_MAX_TABS = 5
            manager.MAX_CONCURRENT_ANONYMOUS = 10
            manager.monitoring_tasks = {}
            manager.anonymous_task_ids = set()
            manager.tab_pool_manager = MagicMock()
            manager.tab_pool_manager.tab_in_use = {}

            # Mock 메서드
            manager._get_active_anonymous_count = MagicMock(return_value=10)  # 가득 참
            manager._get_tab_based_task_count = MagicMock(return_value=2)     # 여유 있음

            # 대기열에 항목 있음
            mock_queue = MagicMock()
            mock_queue.empty.return_value = False
            manager.monitoring_queue = mock_queue

            # 로거 모킹
            with patch("app.shared.browser.monitoring_queue.logger") as mock_logger:
                await manager._check_queue_after_task_completion()

                # "여유 공간 있음" 로그가 출력되어야 함
                log_message = mock_logger.info.call_args[0][0]
                assert "여유 공간 있음" in log_message

    @pytest.mark.asyncio
    async def test_no_space_both_full(self):
        """[Right] Anonymous 가득 + 탭 가득 = 공간 없음"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.TOTAL_MAX_TABS = 5
            manager.MAX_CONCURRENT_ANONYMOUS = 10
            manager.monitoring_tasks = {}
            manager.anonymous_task_ids = set()
            manager.tab_pool_manager = MagicMock()
            manager.tab_pool_manager.tab_in_use = {i: True for i in range(5)}  # 5개 사용 중

            # Mock 메서드
            manager._get_active_anonymous_count = MagicMock(return_value=10)  # 가득 참
            manager._get_tab_based_task_count = MagicMock(return_value=5)     # 가득 참

            # 대기열에 항목 있음
            mock_queue = MagicMock()
            mock_queue.empty.return_value = False
            manager.monitoring_queue = mock_queue

            # 로거 모킹
            with patch("app.shared.browser.monitoring_queue.logger") as mock_logger:
                await manager._check_queue_after_task_completion()

                # "여유 공간 없음" 로그가 출력되어야 함
                log_message = mock_logger.info.call_args[0][0]
                assert "여유 공간 없음" in log_message


class TestAnonymousTaskManagement:
    """Anonymous 태스크 관리 테스트"""

    def test_register_anonymous_task(self):
        """[Right] Anonymous 태스크 등록"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.anonymous_task_ids = set()

            manager._register_anonymous_task(123)

            assert 123 in manager.anonymous_task_ids

    def test_unregister_anonymous_task(self):
        """[Right] Anonymous 태스크 해제"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.anonymous_task_ids = {123, 456}

            manager._unregister_anonymous_task(123)

            assert 123 not in manager.anonymous_task_ids
            assert 456 in manager.anonymous_task_ids

    def test_unregister_nonexistent_task(self):
        """[Error] 존재하지 않는 태스크 해제 시 에러 없음"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.anonymous_task_ids = {123}

            # 존재하지 않는 ID 해제 시도 - 에러 발생하지 않아야 함
            manager._unregister_anonymous_task(999)

            assert 123 in manager.anonymous_task_ids


class TestGetActiveAnonymousCount:
    """_get_active_anonymous_count 테스트"""

    def test_cleans_up_completed_tasks(self):
        """[Right] 완료된 Anonymous 태스크 자동 정리"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        mock_task1 = MagicMock()
        mock_task1.done.return_value = True   # 완료됨
        mock_task2 = MagicMock()
        mock_task2.done.return_value = False  # 실행 중

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.monitoring_tasks = {1: mock_task1, 2: mock_task2}
            manager.anonymous_task_ids = {1, 2}  # 둘 다 Anonymous

            result = manager._get_active_anonymous_count()

            # 완료된 태스크는 정리되고 실행 중인 것만 카운트
            assert result == 1
            assert 1 not in manager.anonymous_task_ids  # 정리됨
            assert 2 in manager.anonymous_task_ids       # 유지됨


# Integration-like tests
class TestTaskLimitIntegration:
    """태스크 제한 통합 테스트 시나리오"""

    def test_scenario_anonymous_9_tab_2(self):
        """[Cross-check] Anonymous 9개 + 탭 2개 = 둘 다 여유 있음"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.TOTAL_MAX_TABS = 5
            manager.MAX_CONCURRENT_ANONYMOUS = 10
            manager.anonymous_task_ids = set(range(1, 10))  # 1~9: Anonymous

            # 태스크 생성 (1~9 Anonymous, 10~11 Tab-based)
            manager.monitoring_tasks = {}
            for i in range(1, 12):
                task = MagicMock()
                task.done.return_value = False
                manager.monitoring_tasks[i] = task

            # 검증
            anon_count = manager._get_active_anonymous_count()
            tab_count = manager._get_tab_based_task_count()

            assert anon_count == 9   # Anonymous 9개
            assert tab_count == 2    # 탭 기반 2개

            # 제한 체크
            has_anon_space = anon_count < manager.MAX_CONCURRENT_ANONYMOUS
            has_tab_space = tab_count < manager.TOTAL_MAX_TABS

            assert has_anon_space is True   # 9 < 10
            assert has_tab_space is True    # 2 < 5

    def test_scenario_anonymous_10_tab_5(self):
        """[Cross-check] Anonymous 10개 + 탭 5개 = 둘 다 가득 참"""
        from app.shared.browser.monitoring_queue import MonitoringQueue

        with patch.object(MonitoringQueue, "__init__", lambda x: None):
            manager = MonitoringQueue()
            manager.TOTAL_MAX_TABS = 5
            manager.MAX_CONCURRENT_ANONYMOUS = 10
            manager.anonymous_task_ids = set(range(1, 11))  # 1~10: Anonymous

            # 태스크 생성 (1~10 Anonymous, 11~15 Tab-based)
            manager.monitoring_tasks = {}
            for i in range(1, 16):
                task = MagicMock()
                task.done.return_value = False
                manager.monitoring_tasks[i] = task

            # 검증
            anon_count = manager._get_active_anonymous_count()
            tab_count = manager._get_tab_based_task_count()

            assert anon_count == 10  # Anonymous 10개
            assert tab_count == 5    # 탭 기반 5개

            # 제한 체크
            has_anon_space = anon_count < manager.MAX_CONCURRENT_ANONYMOUS
            has_tab_space = tab_count < manager.TOTAL_MAX_TABS

            assert has_anon_space is False  # 10 >= 10
            assert has_tab_space is False   # 5 >= 5
