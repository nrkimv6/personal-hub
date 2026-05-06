import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, expect

pytestmark = pytest.mark.e2e


def _skip_public_mode_if_admin(system_mode: str) -> None:
    if system_mode != "public":
        pytest.skip(f"현재 system mode={system_mode} — public E2E 스킵")


def _seed_admin_expo_draft(page: Page) -> None:
    export_record = Path(__file__).resolve().parents[3] / "data" / "expo" / "coffee-expo-2026" / "export-record.json"
    export_record.unlink(missing_ok=True)


def _hydrate_admin_expo_draft(page: Page) -> None:
    page.evaluate(
        """
        () => {
          const payload = {
            prefix: 'Z-',
            startNumber: 1,
            currentNumber: 2,
            padLength: 2,
            step: 1,
            drafts: [
              {
                name: 'Z-01',
                pin: { xNorm: 0.12, yNorm: 0.34 },
                createdAt: '2026-04-20T15:00:00+09:00'
              }
            ]
          };
          localStorage.setItem('expo:coffee-expo-2026:draft', JSON.stringify(payload));
        }
        """
    )
    page.reload()
    page.wait_for_load_state("networkidle")


class TestPublicExpoBoothMap:
    def test_sidebar_navigates_to_expo_booth_map(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(public_frontend_url)
        page.wait_for_load_state("networkidle")
        page.get_by_role("link", name="커피엑스포 2026").click()
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/expo/coffee-expo-2026$"))
        expect(page.get_by_role("heading", name="커피엑스포 2026")).to_be_visible()

    def test_url_restores_selected_booth_and_slot(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026?booth=A-01&slot=open-demo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("싱글 오리진 라인업과 현장 로스팅 샘플링을 진행합니다.").first).to_be_visible()
        expect(page.get_by_role("button", name="10:30 오픈 데모")).to_have_class(re.compile("amber"))

    def test_slot_filter_dims_non_matching_booths(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="10:30 오픈 데모").click()

        expect(page.locator('button[aria-label="A-01 로스터스 랩"]')).to_have_class(re.compile("opacity-100"))
        expect(page.locator('button[aria-label="A-02 밀크 크래프트"]')).to_have_class(re.compile("opacity-30"))

    def test_author_route_redirects_in_public_mode(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/expo/coffee-expo-2026$"))

    def test_events_expo_tab_redirects_back_to_online_for_public(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/events\?tab=online"))

    def test_mobile_sheet_opens_for_selected_booth(self, page: Page, public_frontend_url: str, system_mode: str):
        _skip_public_mode_if_admin(system_mode)

        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")
        page.locator('button[aria-label="A-01 로스터스 랩"]').click()

        expect(page.get_by_role("button", name="닫기", exact=True)).to_be_visible()
        expect(page.get_by_role("dialog").get_by_text("오픈 빈 테이스팅")).to_be_visible()
        assert page.evaluate("() => document.body.style.overflow") == "hidden"


class TestAdminExpoAuthor:
    # Admin author/editor surfaces intentionally keep draft state local-only until save-api is introduced.
    def test_author_page_is_available_in_admin_mode(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r".*/expo/coffee-expo-2026/author$"))
        expect(page.get_by_role("heading", name="커피엑스포 2026 좌표 작성")).to_be_visible()
        expect(page.locator('meta[name="robots"]')).to_have_attribute("content", re.compile("noindex"))

    def test_admin_events_tab_renders_expo_workspace(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="커피엑스포 2026 좌표 작업")).to_be_visible()
        expect(page.get_by_role("link", name="공개 부스맵 열기")).to_be_visible()

    def test_admin_events_tab_renders_pipeline_and_collection_sections(self, page: Page, frontend_url: str):
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="소스 파이프라인 상태")).to_be_visible()
        expect(page.get_by_role("heading", name="수집 현황과 export 흐름")).to_be_visible()

    def test_admin_export_cta_shows_success_feedback(self, page: Page, context: BrowserContext, frontend_url: str):
        _seed_admin_expo_draft(page)
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=frontend_url)
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")
        _hydrate_admin_expo_draft(page)

        export_button = page.get_by_role("button", name="Export JSON (1)")
        expect(export_button).to_be_enabled()
        export_button.click()

        expect(page.get_by_text("1개 draft를 복사하고 export 기록을 저장했습니다.")).to_be_visible()
        assert "coffee-expo-2026" in page.evaluate("() => navigator.clipboard.readText()")

    def test_admin_export_cta_updates_last_exported_timestamp(self, page: Page, context: BrowserContext, frontend_url: str):
        _seed_admin_expo_draft(page)
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=frontend_url)
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")
        _hydrate_admin_expo_draft(page)

        before = page.get_by_text("최근 export:", exact=False)
        expect(before).to_contain_text("기록 없음")

        page.get_by_role("button", name="Export JSON (1)").click()

        after = page.get_by_text("최근 export:", exact=False)
        expect(after).not_to_contain_text("기록 없음")

    def test_admin_export_keeps_unknown_publish_badge_placeholder(self, page: Page, context: BrowserContext, frontend_url: str):
        _seed_admin_expo_draft(page)
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=frontend_url)
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")
        _hydrate_admin_expo_draft(page)

        status = page.get_by_text("publish 상태: unknown")
        expect(status).to_be_visible()

        page.get_by_role("button", name="Export JSON (1)").click()

        expect(status).to_be_visible()

    def test_public_expo_page_does_not_render_admin_operations_sections(
        self, page: Page, public_frontend_url: str, system_mode: str
    ):
        _skip_public_mode_if_admin(system_mode)

        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="소스 파이프라인 상태")).to_have_count(0)
        expect(page.get_by_role("heading", name="수집 현황과 export 흐름")).to_have_count(0)


class TestAdminMapUpload:
    """배치도 업로드 UI 및 public override 반영 E2E (Phase T4 전용 — main 머지 후 실행)."""

    def test_admin_map_upload_panel_is_visible(self, page: Page, frontend_url: str):
        """/events?tab=expo admin 워크스페이스에 업로드 패널이 표시된다."""
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_role("heading", name="배치도 이미지")).to_be_visible()
        expect(page.locator('input[type="file"]')).to_be_attached()

    def test_admin_map_upload_success_shows_preview(self, page: Page, frontend_url: str, tmp_path):
        """PNG 파일 선택 후 업로드 성공 시 미리보기와 성공 피드백이 표시된다."""
        import pathlib

        png_file = tmp_path / "test_map.png"
        png_file.write_bytes(
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx'
            b'\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00'
            b'\x00\x00IEND\xaeB`\x82'
        )

        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")

        page.locator('input[type="file"]').set_input_files(str(png_file))
        page.get_by_role("button", name="업로드").click()

        expect(page.get_by_text("업로드 완료")).to_be_visible(timeout=5000)

    def test_public_page_reads_uploaded_map_override(
        self, page: Page, frontend_url: str, public_frontend_url: str, system_mode: str, tmp_path
    ):
        """admin 업로드 후 public /expo/coffee-expo-2026이 override 이미지를 runtime으로 읽는다."""
        _skip_public_mode_if_admin(system_mode)
        import pathlib

        png_file = tmp_path / "override_map.png"
        png_file.write_bytes(
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx'
            b'\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00'
            b'\x00\x00IEND\xaeB`\x82'
        )

        # admin 업로드
        page.goto(f"{frontend_url}/events?tab=expo")
        page.wait_for_load_state("networkidle")
        page.locator('input[type="file"]').set_input_files(str(png_file))
        page.get_by_role("button", name="업로드").click()
        page.wait_for_selector("text=업로드 완료", timeout=5000)

        # public 페이지에서 override 이미지 src 확인
        page.goto(f"{public_frontend_url}/expo/coffee-expo-2026")
        page.wait_for_load_state("networkidle")

        map_img = page.locator("img[alt]").first
        img_src = map_img.get_attribute("src")
        assert img_src is not None
        assert "/data/expo/" in img_src or "coffee-expo-2026" in img_src


class TestAdminAuthorConflictUX:
    """author 충돌 UX E2E (strict/skip/overwrite 모드, Phase T4 전용 — main 머지 후 실행)."""

    def test_author_strict_mode_shows_collision_block_on_duplicate(
        self, page: Page, frontend_url: str
    ):
        """strict 모드에서 충돌 발생 시 자동 이동하지 않고 인라인 충돌 블록이 표시된다."""
        page.goto(f"{frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        # localStorage에 A-01 draft를 미리 심어 충돌 조건 조성
        page.evaluate(
            """
            () => {
              const payload = {
                prefix: 'A-',
                startNumber: 1,
                currentNumber: 1,
                padLength: 2,
                step: 1,
                drafts: [
                  {
                    name: 'A-01',
                    pin: { xNorm: 0.5, yNorm: 0.5 },
                    createdAt: new Date().toISOString(),
                    source: 'draft'
                  }
                ]
              };
              localStorage.setItem('expo:coffee-expo-2026:draft', JSON.stringify(payload));
            }
            """
        )
        page.reload()
        page.wait_for_load_state("networkidle")

        # strict 모드가 선택되어 있는지 확인
        strict_btn = page.get_by_role("button", name="엄격")
        expect(strict_btn).to_be_visible()

        # 지도를 클릭해 충돌 유발
        map_area = page.get_by_role("button", name="부스 좌표 클릭 영역")
        map_area.click(position={"x": 50, "y": 50})

        # 충돌 블록이 나타나야 함
        expect(page.get_by_text("중복: A-01")).to_be_visible()
        expect(page.get_by_role("button", name="건너뛰기")).to_be_visible()
        expect(page.get_by_role("button", name="덮어쓰기 (좌표 교체)")).to_be_visible()
        expect(page.get_by_role("button", name="취소")).to_be_visible()

    def test_author_skip_mode_advances_to_next_free_number(
        self, page: Page, frontend_url: str
    ):
        """skip 모드에서 충돌 시 다음 빈 번호로 자동 이동하고 '다음 생성 부스명'이 갱신된다."""
        page.goto(f"{frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        page.evaluate(
            """
            () => {
              const payload = {
                prefix: 'A-', startNumber: 1, currentNumber: 1, padLength: 2, step: 1,
                drafts: [{ name: 'A-01', pin: { xNorm: 0.3, yNorm: 0.3 }, createdAt: new Date().toISOString(), source: 'draft' }]
              };
              localStorage.setItem('expo:coffee-expo-2026:draft', JSON.stringify(payload));
              localStorage.setItem('expo:coffee-expo-2026:allocationMode', 'skip');
            }
            """
        )
        page.reload()
        page.wait_for_load_state("networkidle")

        # '다음 생성 부스명'이 A-02(skip된 결과)를 표시해야 함
        expect(page.get_by_text("다음 생성 부스명")).to_be_visible()
        expect(page.get_by_text("A-02")).to_be_visible()

    def test_author_overwrite_mode_moves_existing_pin(
        self, page: Page, frontend_url: str
    ):
        """overwrite 모드에서 기존 A-01 draft 핀이 새 위치로 이동하고 신규 draft가 추가되지 않는다."""
        page.goto(f"{frontend_url}/expo/coffee-expo-2026/author")
        page.wait_for_load_state("networkidle")

        page.evaluate(
            """
            () => {
              const payload = {
                prefix: 'A-', startNumber: 1, currentNumber: 1, padLength: 2, step: 1,
                drafts: [{ name: 'A-01', pin: { xNorm: 0.5, yNorm: 0.5 }, createdAt: new Date().toISOString(), source: 'draft' }]
              };
              localStorage.setItem('expo:coffee-expo-2026:draft', JSON.stringify(payload));
              localStorage.setItem('expo:coffee-expo-2026:allocationMode', 'overwrite');
            }
            """
        )
        page.reload()
        page.wait_for_load_state("networkidle")

        initial_draft_count = page.locator("text=Draft 목록 (1)").count()
        assert initial_draft_count == 1

        # 지도 클릭 (overwrite)
        map_area = page.get_by_role("button", name="부스 좌표 클릭 영역")
        map_area.click(position={"x": 80, "y": 80})

        # draft 수는 여전히 1개여야 함 (신규 추가 없음)
        expect(page.get_by_text("Draft 목록 (1)")).to_be_visible()
        # 덮어쓰기 뱃지가 표시됨
        expect(page.get_by_text("덮어쓰기")).to_be_visible()
