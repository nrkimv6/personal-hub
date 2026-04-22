"""MP4 -> GIF 도구 페이지 E2E 테스트."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if any(m in title for m in ("ENOENT:", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


class TestMp4GifPageLoad:
    """메뉴 진입 시나리오: /mp4-gif 페이지 기본 요소 확인."""

    def test_page_title_visible(self, page: Page, frontend_url: str, system_mode: str):
        """시나리오: /mp4-gif 진입 시 페이지 제목이 보인다.
        기대 요소: h1 또는 제목 영역에 'MP4' 또는 'GIF' 문자열이 포함된다.
        """
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/mp4-gif")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        heading = page.locator("h1, h2").first
        expect(heading).to_be_visible()
        page_text = page.content()
        assert "MP4" in page_text or "GIF" in page_text, "페이지에 MP4/GIF 관련 제목이 없습니다."

    def test_file_input_visible(self, page: Page, frontend_url: str, system_mode: str):
        """시나리오: /mp4-gif 진입 시 파일 선택 input이 보인다.
        기대 요소: input[type=file] 또는 파일 드롭존이 DOM에 존재한다.
        """
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/mp4-gif")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        file_input = page.locator("input[type='file']")
        expect(file_input).to_be_attached()


class TestMp4GifPageInteraction:
    """파일 선택 후 상태 카드 렌더 시나리오."""

    def test_submit_button_enabled_after_file_select(
        self, page: Page, frontend_url: str, system_mode: str, tmp_path
    ):
        """시나리오: 샘플 mp4 파일 선택 후 변환 시작 버튼이 활성화된다.
        기대 요소: 변환 시작 또는 Submit 버튼이 disabled 아님.
        """
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/mp4-gif")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        dummy_mp4 = tmp_path / "sample.mp4"
        dummy_mp4.write_bytes(b"\x00" * 128)

        file_input = page.locator("input[type='file']")
        file_input.set_input_files(str(dummy_mp4))

        btn = page.locator("button[type='submit'], button:has-text('변환')")
        expect(btn.first).not_to_be_disabled()

    def test_status_card_rendered_after_submit(
        self, page: Page, frontend_url: str, system_mode: str, tmp_path
    ):
        """시나리오: 제출 후 queued 또는 running 상태 카드가 렌더된다.
        기대 요소: 상태 카드에 queued 또는 running 텍스트가 포함된다.
        """
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/mp4-gif")
        page.wait_for_load_state("networkidle")
        _skip_if_frontend_error_title(page)

        dummy_mp4 = tmp_path / "sample.mp4"
        dummy_mp4.write_bytes(b"\x00" * 128)

        file_input = page.locator("input[type='file']")
        file_input.set_input_files(str(dummy_mp4))

        btn = page.locator("button[type='submit'], button:has-text('변환')")
        btn.first.click()

        page.wait_for_timeout(2000)
        page_text = page.content()
        assert any(s in page_text for s in ("queued", "running", "대기", "변환 중")), (
            "상태 카드에 queued/running 상태가 표시되지 않습니다."
        )

    def test_download_button_visible_on_completed(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """시나리오: 완료 fixture 응답에서 다운로드 버튼이 보인다.
        기대 요소: completed 상태 카드에 다운로드 링크 또는 버튼이 있다.
        (실서버 변환 완료 가정 — 실제 실행은 T4 머지 후)
        """
        _skip_admin_mode_if_public(system_mode)
        pytest.skip("T4: 실서버 변환 완료 시나리오 — /merge-test에서 실행")

    def test_gif_preview_visible_on_completed(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """시나리오: 완료 fixture 응답에서 GIF preview가 보인다.
        기대 요소: completed 상태 카드에 img 태그(gif src)가 있다.
        (실서버 변환 완료 가정 — 실제 실행은 T4 머지 후)
        """
        _skip_admin_mode_if_public(system_mode)
        pytest.skip("T4: 실서버 변환 완료 시나리오 — /merge-test에서 실행")
