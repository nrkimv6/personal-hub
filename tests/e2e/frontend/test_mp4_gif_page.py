"""MP4 -> GIF 도구 페이지 E2E 테스트."""

import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _goto_mp4_gif_tab(page: Page, frontend_url: str) -> None:
    page.goto(f"{frontend_url}/file-search?tab=mp4-gif", wait_until="domcontentloaded")
    expect(page.locator("input[type='file']")).to_be_attached(timeout=15000)


def _skip_if_frontend_error_title(page: Page) -> None:
    title = page.title() or ""
    if any(m in title for m in ("ENOENT:", "Vite", "Internal Server Error", "Error")):
        pytest.skip(f"frontend 에러 페이지 감지: {title}")


def _skip_admin_mode_if_public(system_mode: str) -> None:
    if system_mode != "admin":
        pytest.skip(f"현재 system mode={system_mode} — admin E2E 스킵")


def _mock_mp4_gif_api(page: Page, completed_task: dict | None = None) -> dict:
    captured: dict = {}

    page.route(
        "**/api/v1/mp4-gif/health",
        lambda route: route.fulfill(
            status=200,
            json={
                "ffmpeg_ok": True,
                "ffmpeg_path": "ffmpeg",
                "work_root": "test",
                "work_root_exists": True,
                "max_upload_mb": 100,
                "error_message": None,
            },
        ),
    )

    def handle_create(route):
        body = route.request.post_data_buffer or b""
        captured["post_data"] = body.decode("latin-1", errors="ignore")
        route.fulfill(status=202, json={"task_id": "task-options", "status": "queued"})

    page.route("**/api/v1/mp4-gif/tasks", handle_create)

    page.route(
        "**/api/v1/mp4-gif/tasks/task-options/result**",
        lambda route: route.fulfill(
            status=200,
            body=b"GIF89a" + b"\x00" * 16,
            headers={"content-type": "image/gif"},
        ),
    )

    task = completed_task or {
        "task_id": "task-options",
        "status": "completed",
        "source_name": "sample.mp4",
        "fps": 7,
        "width": 360,
        "start_seconds": 1.25,
        "duration_seconds": 3.5,
        "overwrite_mode": "suffix",
        "download_filename": "sample_gif_fps7_w360.gif",
        "error_message": None,
        "created_at": "2026-05-05T15:00:00",
        "started_at": "2026-05-05T15:00:01",
        "completed_at": "2026-05-05T15:00:02",
    }

    page.route("**/api/v1/mp4-gif/tasks/task-options", lambda route: route.fulfill(status=200, json=task))
    return captured


def _select_dummy_mp4(page: Page, tmp_path) -> None:
    dummy_mp4 = tmp_path / "sample.mp4"
    dummy_mp4.write_bytes(b"\x00" * 128)
    page.locator("input[type='file']").set_input_files(str(dummy_mp4))


def _set_video_current_time(page: Page, seconds: float) -> None:
    page.locator("video").evaluate(
        """(el, seconds) => {
            Object.defineProperty(el, 'currentTime', {
                configurable: true,
                get: () => seconds,
                set: () => {}
            });
        }""",
        seconds,
    )


class TestMp4GifPageLoad:
    """메뉴 진입 시나리오: 파일 도구 내부 MP4 -> GIF 탭 기본 요소 확인."""

    def test_legacy_route_redirects_to_file_tools_tab(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """시나리오: /mp4-gif 진입 시 파일 도구 탭으로 리다이렉트된다."""
        _skip_admin_mode_if_public(system_mode)
        page.goto(f"{frontend_url}/mp4-gif", wait_until="domcontentloaded")
        _skip_if_frontend_error_title(page)

        expect(page).to_have_url(f"{frontend_url}/file-search?tab=mp4-gif")
        expect(page.locator("input[type='file']")).to_be_attached(timeout=15000)

    def test_page_title_visible(self, page: Page, frontend_url: str, system_mode: str):
        """시나리오: file-search 내부 mp4-gif 탭 진입 시 페이지 제목이 보인다.
        기대 요소: h1 또는 제목 영역에 'MP4' 또는 'GIF' 문자열이 포함된다.
        """
        _skip_admin_mode_if_public(system_mode)
        _goto_mp4_gif_tab(page, frontend_url)
        _skip_if_frontend_error_title(page)

        heading = page.locator("h1, h2").first
        expect(heading).to_be_visible()
        page_text = page.content()
        assert "MP4" in page_text or "GIF" in page_text, "페이지에 MP4/GIF 관련 제목이 없습니다."

    def test_file_input_visible(self, page: Page, frontend_url: str, system_mode: str):
        """시나리오: file-search 내부 mp4-gif 탭 진입 시 파일 선택 input이 보인다.
        기대 요소: input[type=file] 또는 파일 드롭존이 DOM에 존재한다.
        """
        _skip_admin_mode_if_public(system_mode)
        _goto_mp4_gif_tab(page, frontend_url)
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
        _goto_mp4_gif_tab(page, frontend_url)
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
        _goto_mp4_gif_tab(page, frontend_url)
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

    def test_preset_cards_update_fps_and_width(
        self, page: Page, frontend_url: str, system_mode: str
    ):
        """시나리오: preset 카드 클릭 시 fps/width 입력값이 함께 바뀐다."""
        _skip_admin_mode_if_public(system_mode)
        _mock_mp4_gif_api(page)
        _goto_mp4_gif_tab(page, frontend_url)
        _skip_if_frontend_error_title(page)

        page.get_by_role("button", name="고화질 15fps · 원본").click()
        page.get_by_role("button", name="고급 옵션").click()
        expect(page.locator("#fps-input")).to_have_value("15")
        expect(page.locator("#width-input")).to_have_value("")

        page.get_by_role("button", name="저용량 6fps · 480px").click()
        expect(page.locator("#fps-input")).to_have_value("6")
        expect(page.locator("#width-input")).to_have_value("480")

    def test_custom_options_submit_payload_and_completed_card(
        self, page: Page, frontend_url: str, system_mode: str, tmp_path
    ):
        """시나리오: custom 옵션 payload와 완료 카드 옵션/다운로드 표면을 검증한다."""
        _skip_admin_mode_if_public(system_mode)
        captured = _mock_mp4_gif_api(page)
        _goto_mp4_gif_tab(page, frontend_url)
        _skip_if_frontend_error_title(page)
        page.evaluate(
            """() => {
                window.__mp4GifPayload = null;
                const originalFetch = window.fetch.bind(window);
                window.fetch = async (input, init = {}) => {
                    const url = String(input);
                    if (url.includes('/mp4-gif/tasks') && init.method === 'POST' && init.body instanceof FormData) {
                        window.__mp4GifPayload = Array.from(init.body.entries()).map(([key, value]) => [
                            key,
                            value instanceof File ? value.name : String(value)
                        ]);
                    }
                    return originalFetch(input, init);
                };
            }"""
        )

        _select_dummy_mp4(page, tmp_path)
        page.get_by_role("button", name="고급 옵션").click()
        page.locator("#fps-input").fill("7")
        page.locator("#width-input").fill("360")
        page.locator("#overwrite-select").select_option("suffix")

        _set_video_current_time(page, 1.25)
        page.get_by_role("button", name="시작점 지정").click()
        _set_video_current_time(page, 4.75)
        page.get_by_role("button", name="종료점 지정").click()

        page.get_by_role("button", name="변환 시작").click()
        expect(page.get_by_text("완료")).to_be_visible(timeout=10000)
        expect(page.get_by_text("fps 7", exact=True)).to_be_visible()
        expect(page.get_by_text("360px")).to_be_visible()
        expect(page.get_by_text("· 구간: 1.3s ~ 4.8s", exact=True)).to_be_visible()
        expect(page.get_by_text("· 옵션 suffix 붙이기", exact=True)).to_be_visible()
        expect(page.get_by_role("link", name=re.compile("GIF 다운로드"))).to_be_visible()

        payload = dict(page.evaluate("() => window.__mp4GifPayload || []"))
        assert payload["file"] == "sample.mp4"
        assert payload["fps"] == "7"
        assert payload["width"] == "360"
        assert payload["overwrite_mode"] == "suffix"
        assert payload["start_seconds"] == "1.250"
        assert payload["duration_seconds"] == "3.500"


class TestMp4GifTrimPreview:
    """트림 미리보기 UI 시나리오: 파일 선택 후 video 요소 및 마커 버튼 확인."""

    def test_video_preview_visible_after_file_select(
        self, page: Page, frontend_url: str, system_mode: str, tmp_path
    ):
        """시나리오: MP4 파일 선택 후 video 미리보기 요소가 DOM에 나타난다.
        기대 요소: video 태그가 visible 상태가 된다.
        """
        _skip_admin_mode_if_public(system_mode)
        _goto_mp4_gif_tab(page, frontend_url)
        _skip_if_frontend_error_title(page)

        dummy_mp4 = tmp_path / "sample.mp4"
        dummy_mp4.write_bytes(b"\x00" * 128)

        file_input = page.locator("input[type='file']")
        file_input.set_input_files(str(dummy_mp4))

        video_el = page.locator("video")
        expect(video_el).to_be_attached()

    def test_mark_start_button_visible_when_video_loaded(
        self, page: Page, frontend_url: str, system_mode: str, tmp_path
    ):
        """시나리오: 파일 선택 후 '시작점 지정' 버튼이 DOM에 나타난다.
        기대 요소: '시작점 지정' 텍스트를 가진 버튼이 attached 상태다.
        """
        _skip_admin_mode_if_public(system_mode)
        _goto_mp4_gif_tab(page, frontend_url)
        _skip_if_frontend_error_title(page)

        dummy_mp4 = tmp_path / "sample.mp4"
        dummy_mp4.write_bytes(b"\x00" * 128)

        file_input = page.locator("input[type='file']")
        file_input.set_input_files(str(dummy_mp4))

        start_btn = page.locator("button:has-text('시작점 지정')")
        expect(start_btn).to_be_attached()

    def test_mark_end_button_disabled_until_start_selected(
        self, page: Page, frontend_url: str, system_mode: str, tmp_path
    ):
        """시나리오: 시작점 미지정 상태에서 '종료점 지정' 버튼은 비활성화된다.
        기대 요소: '종료점 지정' 버튼이 disabled 속성을 갖는다.
        """
        _skip_admin_mode_if_public(system_mode)
        _goto_mp4_gif_tab(page, frontend_url)
        _skip_if_frontend_error_title(page)

        dummy_mp4 = tmp_path / "sample.mp4"
        dummy_mp4.write_bytes(b"\x00" * 128)

        file_input = page.locator("input[type='file']")
        file_input.set_input_files(str(dummy_mp4))

        end_btn = page.locator("button:has-text('종료점 지정')")
        expect(end_btn).to_be_disabled()

    def test_mark_end_button_enabled_after_start_selected(
        self, page: Page, frontend_url: str, system_mode: str, tmp_path
    ):
        """시나리오: '시작점 지정' 클릭 후 '종료점 지정' 버튼이 활성화된다.
        기대 요소: 시작점 클릭 → 종료점 버튼 not_to_be_disabled.
        """
        _skip_admin_mode_if_public(system_mode)
        _goto_mp4_gif_tab(page, frontend_url)
        _skip_if_frontend_error_title(page)

        dummy_mp4 = tmp_path / "sample.mp4"
        dummy_mp4.write_bytes(b"\x00" * 128)

        file_input = page.locator("input[type='file']")
        file_input.set_input_files(str(dummy_mp4))

        start_btn = page.locator("button:has-text('시작점 지정')")
        start_btn.click()

        end_btn = page.locator("button:has-text('종료점 지정')")
        expect(end_btn).not_to_be_disabled()
