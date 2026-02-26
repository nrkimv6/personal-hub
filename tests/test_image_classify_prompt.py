"""_build_classify_prompt() provider 분기 TC.

테스트 범위:
1. provider="gemini" 시 Read 도구 언급 없는 프롬프트 생성
2. provider="claude" 시 Read 도구 포함 프롬프트 생성 (기존 동작 유지)
3. provider 기본값이 "claude" 동작임을 검증
"""

import sys
import unittest
from pathlib import Path

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestBuildClassifyPrompt(unittest.TestCase):
    """_build_classify_prompt() provider 분기 검증."""

    @classmethod
    def setUpClass(cls):
        from app.modules.image_classifier.routers.classify import _build_classify_prompt
        cls.build = staticmethod(_build_classify_prompt)

    def test_gemini_prompt_no_read_tool(self):
        """provider='gemini' 시 'Read 도구' 언급 없음, '첨부된 이미지' 포함."""
        result = self.build(["카테고리A", "카테고리B"], "/path/57.jpg", provider="gemini")

        self.assertNotIn("Read 도구", result, "Gemini 프롬프트에 'Read 도구' 가 없어야 한다.")
        self.assertIn("첨부된 이미지", result, "Gemini 프롬프트에 '첨부된 이미지' 가 포함돼야 한다.")

    def test_gemini_prompt_no_file_path(self):
        """provider='gemini' 시 이미지 파일 경로가 프롬프트 본문에 포함되지 않음."""
        image_path = "/path/to/57.jpg"
        result = self.build(["카테고리A"], image_path, provider="gemini")

        # gemini는 @경로로 별도 첨부 — 프롬프트 본문에 경로 노출 불필요
        self.assertNotIn(image_path, result, "Gemini 프롬프트 본문에 파일 경로가 포함되면 안 된다.")

    def test_claude_prompt_has_read_tool(self):
        """provider='claude' 시 'Read 도구' 포함, '첨부된 이미지' 없음."""
        result = self.build(["카테고리A"], "/path/57.jpg", provider="claude")

        self.assertIn("Read 도구", result, "Claude 프롬프트에 'Read 도구' 가 포함돼야 한다.")
        self.assertNotIn("첨부된 이미지", result, "Claude 프롬프트에 '첨부된 이미지' 가 없어야 한다.")

    def test_claude_prompt_has_file_path(self):
        """provider='claude' 시 이미지 파일 경로가 프롬프트 본문에 포함됨."""
        image_path = "/path/to/57.jpg"
        result = self.build(["카테고리A"], image_path, provider="claude")

        self.assertIn(image_path, result, "Claude 프롬프트 본문에 파일 경로가 포함돼야 한다.")

    def test_default_provider_is_claude(self):
        """provider 파라미터 생략 시 claude 동작 (Read 도구 포함)."""
        result = self.build(["카테고리A"], "/path/57.jpg")

        self.assertIn("Read 도구", result, "기본값(provider 생략)은 claude 동작이어야 한다.")

    def test_categories_included_in_both_providers(self):
        """categories 목록이 gemini/claude 모두 프롬프트에 포함됨."""
        cats = ["고양이", "강아지", "기타"]
        for provider in ("gemini", "claude"):
            result = self.build(cats, "/img.jpg", provider=provider)
            for cat in cats:
                self.assertIn(cat, result, f"provider={provider}: 카테고리 '{cat}'가 프롬프트에 없다.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
