"""
자동화 감지 우회 스크립트 테스트

목적: ContextManager의 _get_anti_detection_script 메서드가 올바른 JavaScript를 반환하는지 검증

RIGHT-BICEP 원칙:
- Right: 스크립트가 올바른 형식인가?
- Boundary: 빈 스크립트, 특수 문자 처리
- Inverse: N/A (단방향 생성)
- Cross-check: JavaScript 구문 유효성
- Error: 에러 없이 실행되는가?
- Performance: N/A (단순 문자열 반환)

CORRECT 조건:
- Conformance: JavaScript 문법 준수
- Ordering: N/A
- Range: N/A
- Reference: N/A
- Existence: 필수 우회 로직 존재
- Cardinality: 우회 항목 개수
- Time: N/A
"""

import pytest
import re
from unittest.mock import MagicMock, AsyncMock, patch


class TestAntiDetectionScript:
    """
    자동화 감지 우회 스크립트 테스트

    CORRECT - Existence: 필수 우회 로직 존재
    CORRECT - Conformance: JavaScript 문법 준수
    """

    @pytest.fixture
    def context_manager(self):
        """ContextManager 인스턴스"""
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    # ============================================================
    # 1. 스크립트 기본 검증 (Right, Existence)
    # ============================================================

    def test_right_script_returns_string(self, context_manager):
        """[Right] 스크립트가 문자열을 반환해야 함"""
        script = context_manager._get_anti_detection_script()
        assert isinstance(script, str)
        assert len(script) > 0

    def test_existence_navigator_webdriver_bypass(self, context_manager):
        """[Existence] navigator.webdriver 우회 로직이 존재해야 함"""
        script = context_manager._get_anti_detection_script()

        # undefined로 설정하는 로직 확인
        assert "navigator.webdriver" in script
        assert "undefined" in script
        # 프로토타입에서 삭제 시도
        assert "Object.getPrototypeOf(navigator).webdriver" in script

    def test_existence_window_chrome_spoofing(self, context_manager):
        """[Existence] window.chrome 스푸핑 로직이 존재해야 함"""
        script = context_manager._get_anti_detection_script()

        assert "window.chrome" in script
        assert "runtime" in script
        assert "loadTimes" in script
        assert "csi" in script
        assert "app" in script

    def test_existence_permissions_query_spoofing(self, context_manager):
        """[Existence] navigator.permissions.query 스푸핑 로직이 존재해야 함"""
        script = context_manager._get_anti_detection_script()

        assert "navigator.permissions.query" in script
        assert "notifications" in script

    def test_existence_plugins_spoofing(self, context_manager):
        """[Existence] navigator.plugins 스푸핑 로직이 존재해야 함"""
        script = context_manager._get_anti_detection_script()

        assert "navigator.plugins" in script
        # 실제 플러그인 이름들
        assert "Chrome PDF Plugin" in script
        assert "Chrome PDF Viewer" in script
        assert "Native Client" in script

    def test_existence_languages_spoofing(self, context_manager):
        """[Existence] navigator.languages 스푸핑 로직이 존재해야 함"""
        script = context_manager._get_anti_detection_script()

        assert "navigator.languages" in script
        assert "ko-KR" in script
        assert "ko" in script

    def test_existence_max_touch_points(self, context_manager):
        """[Existence] navigator.maxTouchPoints 설정이 존재해야 함"""
        script = context_manager._get_anti_detection_script()

        assert "maxTouchPoints" in script

    # ============================================================
    # 2. JavaScript 문법 검증 (Conformance)
    # ============================================================

    def test_conformance_balanced_braces(self, context_manager):
        """[Conformance] 중괄호가 균형을 이루어야 함"""
        script = context_manager._get_anti_detection_script()

        open_braces = script.count('{')
        close_braces = script.count('}')
        assert open_braces == close_braces, f"Unbalanced braces: {open_braces} {{ vs {close_braces} }}"

    def test_conformance_balanced_parentheses(self, context_manager):
        """[Conformance] 괄호가 균형을 이루어야 함"""
        script = context_manager._get_anti_detection_script()

        open_parens = script.count('(')
        close_parens = script.count(')')
        assert open_parens == close_parens, f"Unbalanced parentheses: {open_parens} ( vs {close_parens} )"

    def test_conformance_balanced_brackets(self, context_manager):
        """[Conformance] 대괄호가 균형을 이루어야 함"""
        script = context_manager._get_anti_detection_script()

        open_brackets = script.count('[')
        close_brackets = script.count(']')
        assert open_brackets == close_brackets, f"Unbalanced brackets: {open_brackets} [ vs {close_brackets} ]"

    def test_conformance_no_syntax_errors_pattern(self, context_manager):
        """[Conformance] 일반적인 JavaScript 구문 오류 패턴이 없어야 함"""
        script = context_manager._get_anti_detection_script()

        # 이중 세미콜론
        assert ";;" not in script
        # 빈 함수 호출 뒤 점
        assert "()." not in script.replace("function()", "")

    def test_conformance_object_define_property_syntax(self, context_manager):
        """[Conformance] Object.defineProperty 구문이 올바른 형식이어야 함"""
        script = context_manager._get_anti_detection_script()

        # Object.defineProperty 패턴 확인
        define_property_pattern = r"Object\.defineProperty\s*\(\s*\w+"
        matches = re.findall(define_property_pattern, script)
        assert len(matches) >= 4, "Should have at least 4 Object.defineProperty calls"

    # ============================================================
    # 3. 스크립트 개선 사항 검증 (Right - 개선된 로직)
    # ============================================================

    def test_right_webdriver_undefined_not_false(self, context_manager):
        """[Right] webdriver가 false가 아닌 undefined로 설정되어야 함"""
        script = context_manager._get_anti_detection_script()

        # 기존 문제: get: () => false
        # 개선안: get: () => undefined
        webdriver_section = script[script.find("navigator.webdriver"):script.find("navigator.webdriver") + 200]

        assert "undefined" in webdriver_section
        # false가 직접적으로 webdriver 값으로 설정되면 안 됨
        # (단, 조건문 등에서의 false 사용은 허용)

    def test_right_plugins_have_realistic_structure(self, context_manager):
        """[Right] plugins가 실제 플러그인처럼 name, filename, description을 가져야 함"""
        script = context_manager._get_anti_detection_script()

        # plugins 섹션에서 필수 속성 확인
        plugins_section = script[script.find("navigator.plugins"):script.find("navigator.plugins") + 500]

        assert "name:" in plugins_section or "'name'" in plugins_section or '"name"' in plugins_section
        assert "filename:" in plugins_section or "'filename'" in plugins_section or '"filename"' in plugins_section

    def test_right_try_catch_for_prototype_deletion(self, context_manager):
        """[Right] 프로토타입 삭제는 try-catch로 감싸야 함"""
        script = context_manager._get_anti_detection_script()

        # 프로토타입 삭제가 try-catch 안에 있는지 확인
        prototype_index = script.find("Object.getPrototypeOf(navigator).webdriver")
        if prototype_index != -1:
            # 앞쪽에 try가 있어야 함
            before_section = script[max(0, prototype_index - 100):prototype_index]
            assert "try" in before_section, "Prototype deletion should be wrapped in try-catch"

    # ============================================================
    # 4. 카디널리티 테스트 (Cardinality)
    # ============================================================

    def test_cardinality_minimum_bypass_count(self, context_manager):
        """[Cardinality] 최소 6개의 우회 항목이 있어야 함"""
        script = context_manager._get_anti_detection_script()

        bypass_items = [
            "navigator.webdriver",
            "window.chrome",
            "navigator.permissions.query",
            "navigator.plugins",
            "navigator.languages",
            "maxTouchPoints"
        ]

        found_items = sum(1 for item in bypass_items if item in script)
        assert found_items >= 6, f"Only found {found_items} bypass items, expected at least 6"

    def test_cardinality_plugins_count(self, context_manager):
        """[Cardinality] 최소 3개의 가짜 플러그인이 있어야 함"""
        script = context_manager._get_anti_detection_script()

        plugin_names = ["Chrome PDF Plugin", "Chrome PDF Viewer", "Native Client"]
        found_plugins = sum(1 for name in plugin_names if name in script)

        assert found_plugins >= 3, f"Only found {found_plugins} plugins, expected at least 3"

    def test_cardinality_languages_count(self, context_manager):
        """[Cardinality] 최소 2개의 언어가 설정되어야 함"""
        script = context_manager._get_anti_detection_script()

        languages = ["ko-KR", "ko", "en-US", "en"]
        found_languages = sum(1 for lang in languages if lang in script)

        assert found_languages >= 2, f"Only found {found_languages} languages, expected at least 2"


class TestBypassAutomationDetection:
    """
    _bypass_automation_detection 메서드 통합 테스트

    RIGHT-BICEP - Right: 올바른 동작
    RIGHT-BICEP - Error: 에러 처리
    """

    @pytest.fixture
    def context_manager(self):
        """ContextManager 인스턴스"""
        from app.shared.browser.context_manager import ContextManager
        return ContextManager()

    @pytest.mark.asyncio
    async def test_right_calls_add_init_script(self, context_manager):
        """[Right] _bypass_automation_detection이 add_init_script를 호출해야 함"""
        mock_context = MagicMock()
        mock_context.add_init_script = AsyncMock()

        await context_manager._bypass_automation_detection(mock_context)

        mock_context.add_init_script.assert_called_once()
        # 호출된 스크립트가 _get_anti_detection_script 결과와 일치하는지
        called_script = mock_context.add_init_script.call_args[0][0]
        expected_script = context_manager._get_anti_detection_script()
        assert called_script == expected_script

    @pytest.mark.asyncio
    async def test_error_handles_add_init_script_failure(self, context_manager):
        """[Error] add_init_script 실패 시 예외가 전파되어야 함"""
        mock_context = MagicMock()
        mock_context.add_init_script = AsyncMock(side_effect=Exception("Script injection failed"))

        with pytest.raises(Exception, match="Script injection failed"):
            await context_manager._bypass_automation_detection(mock_context)


class TestGetAntiDetectionScriptStaticMethod:
    """
    _get_anti_detection_script 정적 메서드 테스트

    CORRECT - Conformance: 정적 메서드로 정의됨
    """

    def test_conformance_is_static_method(self):
        """[Conformance] _get_anti_detection_script가 정적 메서드여야 함"""
        from app.shared.browser.context_manager import ContextManager

        # 클래스에서 직접 호출 가능해야 함
        script = ContextManager._get_anti_detection_script()
        assert isinstance(script, str)

    def test_conformance_callable_without_instance(self):
        """[Conformance] 인스턴스 없이 호출 가능해야 함"""
        from app.shared.browser.context_manager import ContextManager

        # 인스턴스 생성 없이 호출
        script = ContextManager._get_anti_detection_script()
        assert len(script) > 100  # 충분히 긴 스크립트


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
