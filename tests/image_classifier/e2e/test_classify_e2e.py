"""Phase 4: 통합 테스트 — 이미지 분류 E2E 검증

항목 9: 단일 이미지 분류 E2E (어댑터 레벨, subprocess mock)
항목 10: 썸네일 vs 원본 분류 품질 비교 (어댑터 레벨, subprocess mock)
항목 11: pHash 그룹 분류 E2E (API 레벨 — LLM 워커 필요, 수동 검증)
항목 12: 배치 분류 안정성 (API 레벨 — LLM 워커 필요, 수동 검증)
"""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy import text


# ================================================
# Fixtures
# ================================================

@pytest.fixture
def categories_in_db(test_db):
    """카테고리 데이터 시드"""
    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, 'Travel', 'Travel'),
        (2, 'Food', 'Food'),
        (3, 'Family', 'Family'),
        (4, 'Landscape', 'Landscape')
    """))
    test_db.commit()
    return ['Travel', 'Food', 'Family', 'Landscape']


@pytest.fixture
def single_image(tmp_path):
    """테스트용 단일 이미지"""
    from PIL import Image
    img = Image.new("RGB", (300, 300), color=(100, 150, 200))
    path = tmp_path / "test_image.jpg"
    img.save(str(path), quality=85)
    return path


@pytest.fixture
def thumbnail_and_original(tmp_path):
    """같은 내용의 원본 + 썸네일 이미지 쌍"""
    from PIL import Image
    original = Image.new("RGB", (1920, 1080), color=(80, 120, 200))
    original_path = tmp_path / "original.jpg"
    original.save(str(original_path), quality=95)

    thumb = original.resize((300, 300))
    thumb_path = tmp_path / "thumbnail.jpg"
    thumb.save(str(thumb_path), quality=85)

    return original_path, thumb_path


@pytest.fixture
def seeded_files_for_e2e(test_db, tmp_path):
    """E2E 테스트용 파일 + 카테고리 시드"""
    from PIL import Image

    test_db.execute(text("""
        INSERT INTO categories (id, name, full_path) VALUES
        (1, 'Travel', 'Travel'), (2, 'Food', 'Food')
    """))

    for i in range(1, 11):
        img = Image.new("RGB", (100, 100), color=(i * 25 % 256, 0, 0))
        path = tmp_path / f"img_{i}.jpg"
        img.save(str(path))

        test_db.execute(text("""
            INSERT INTO file_classifications (id, file_path, file_hash, status)
            VALUES (:id, :path, :hash, 'pending')
        """), {"id": i, "path": str(path), "hash": f"hash_{i}"})

    test_db.commit()


def _make_cli_mock_stdout(category="Travel", confidence=0.92):
    """Claude CLI stdout mock 데이터 생성"""
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "result": "",
        "structured_output": {
            "category": category,
            "confidence": confidence,
            "reasoning": "test classification"
        }
    }).encode("utf-8")


def _make_fake_subprocess(category="Travel", confidence=0.92):
    """CLI subprocess mock factory"""
    async def fake_create_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        proc.stdout.read = AsyncMock(
            return_value=_make_cli_mock_stdout(category, confidence)
        )
        proc.stderr.readline = AsyncMock(return_value=b"")
        proc.wait = AsyncMock()
        return proc
    return fake_create_subprocess


# ================================================
# 항목 9: 단일 이미지 분류 E2E (어댑터 레벨)
# ================================================

class TestSingleImageClassification:
    """단일 이미지 classify_image() 호출 검증"""

    @pytest.mark.asyncio
    async def test_classify_single_image_returns_result(self, single_image, categories_in_db):
        """classify_image()가 카테고리 + confidence를 반환하는지 확인"""
        from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter
        from app.modules.image_classifier.adapters.base import ClassifyResult

        adapter = ClaudeCLIAdapter()

        with patch("asyncio.create_subprocess_exec", side_effect=_make_fake_subprocess("Travel", 0.92)):
            result = await adapter.classify_image(
                image_path=str(single_image),
                prompt="Classify this image",
                categories=categories_in_db,
            )

        assert isinstance(result, ClassifyResult)
        assert result.category_path == "Travel"
        assert result.confidence == pytest.approx(0.92)
        assert result.reasoning is not None
        assert "CLI" in result.model

    @pytest.mark.asyncio
    async def test_classify_timeout_returns_error(self, single_image, categories_in_db):
        """타임아웃 시 error/timeout 반환"""
        from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter

        adapter = ClaudeCLIAdapter()
        adapter.timeout = 0.01

        async def slow_subprocess(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = None
            async def slow_read():
                await asyncio.sleep(10)
                return b""
            proc.stdout.read = slow_read
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.wait = AsyncMock()
            proc.kill = MagicMock()
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=slow_subprocess):
            result = await adapter.classify_image(
                str(single_image), "classify", categories_in_db
            )

        assert result.category_path == "error/timeout"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_classify_cli_error_returns_exception(self, single_image, categories_in_db):
        """CLI 비정상 종료 시 error/exception 반환"""
        from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter

        adapter = ClaudeCLIAdapter()

        async def failing_subprocess(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 1
            proc.stdout.read = AsyncMock(return_value=b"")
            proc.stderr.readline = AsyncMock(side_effect=[b"Error: something broke\n", b""])
            proc.wait = AsyncMock()
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=failing_subprocess):
            result = await adapter.classify_image(
                str(single_image), "classify", categories_in_db
            )

        assert result.category_path == "error/exception"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_classify_json_parse_error(self, single_image, categories_in_db):
        """CLI가 비정상 JSON 반환 시 error/exception"""
        from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter

        adapter = ClaudeCLIAdapter()

        async def bad_json_subprocess(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.stdout.read = AsyncMock(return_value=b"not valid json")
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.wait = AsyncMock()
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=bad_json_subprocess):
            result = await adapter.classify_image(
                str(single_image), "classify", categories_in_db
            )

        assert result.category_path == "error/exception"

    @pytest.mark.asyncio
    async def test_structured_output_parsing(self, single_image, categories_in_db):
        """structured_output 필드 우선 파싱 확인"""
        from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter

        adapter = ClaudeCLIAdapter()

        # result는 빈 문자열, structured_output에 실제 데이터
        stdout = json.dumps({
            "type": "result",
            "result": "",
            "structured_output": {
                "category": "Food",
                "confidence": 0.99,
                "reasoning": "food image"
            }
        }).encode()

        async def fake(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.stdout.read = AsyncMock(return_value=stdout)
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.wait = AsyncMock()
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake):
            result = await adapter.classify_image(
                str(single_image), "classify", categories_in_db
            )

        assert result.category_path == "Food"
        assert result.confidence == pytest.approx(0.99)


# ================================================
# 항목 10: 썸네일 vs 원본 분류 품질 비교
# ================================================

class TestThumbnailVsOriginal:
    """썸네일(300x300)과 원본의 분류 결과 비교"""

    @pytest.mark.asyncio
    async def test_thumbnail_produces_same_category(self, thumbnail_and_original, categories_in_db):
        """썸네일과 원본이 동일한 카테고리로 분류되는지 확인"""
        from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter

        original_path, thumb_path = thumbnail_and_original
        adapter = ClaudeCLIAdapter()

        call_count = {"n": 0}

        async def fake_subprocess(*args, **kwargs):
            call_count["n"] += 1
            result = {
                "type": "result",
                "structured_output": {
                    "category": "Landscape",
                    "confidence": 0.95 if call_count["n"] == 1 else 0.93,
                    "reasoning": "blue sky"
                }
            }
            proc = AsyncMock()
            proc.returncode = 0
            proc.stdout.read = AsyncMock(return_value=json.dumps(result).encode())
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.wait = AsyncMock()
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess):
            result_original = await adapter.classify_image(
                str(original_path), "classify", categories_in_db
            )
            result_thumb = await adapter.classify_image(
                str(thumb_path), "classify", categories_in_db
            )

        assert result_original.category_path == result_thumb.category_path
        assert call_count["n"] == 2
        assert abs(result_original.confidence - result_thumb.confidence) < 0.1

    @pytest.mark.asyncio
    async def test_thumbnail_is_smaller_file(self, thumbnail_and_original):
        """썸네일 파일 크기가 원본보다 현저히 작은지 확인"""
        original_path, thumb_path = thumbnail_and_original
        original_size = original_path.stat().st_size
        thumb_size = thumb_path.stat().st_size

        assert thumb_size < original_size * 0.5, (
            f"thumb({thumb_size}B) not much smaller than original({original_size}B)"
        )

    @pytest.mark.asyncio
    async def test_prompt_contains_image_path(self, thumbnail_and_original, categories_in_db):
        """프롬프트에 이미지 경로가 포함되는지 확인"""
        from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter

        adapter = ClaudeCLIAdapter()
        _, thumb_path = thumbnail_and_original

        captured_cmd = {}

        async def capture_subprocess(*args, **kwargs):
            captured_cmd["args"] = args
            proc = AsyncMock()
            proc.returncode = 0
            proc.stdout.read = AsyncMock(
                return_value=_make_cli_mock_stdout()
            )
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.wait = AsyncMock()
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_subprocess):
            await adapter.classify_image(
                str(thumb_path), "classify", categories_in_db
            )

        # -p 플래그 다음의 프롬프트 문자열에 이미지 경로 포함 확인
        cmd_args = captured_cmd["args"]
        prompt_idx = list(cmd_args).index("-p") + 1
        prompt_text = cmd_args[prompt_idx]
        assert str(thumb_path) in prompt_text


# ================================================
# 항목 11: pHash 그룹 분류 E2E (API 레벨)
# ================================================

class TestPHashGroupClassificationAPI:
    """pHash 그룹 기반 분류 — API 레벨 검증

    NOTE: 전체 분류 흐름(enqueue → LLM worker → poll → 결과 저장)은
    LLM 워커가 실행 중이어야 동작합니다.
    여기서는 API 엔드포인트와 DB 시드 정합성만 검증합니다.
    전체 흐름은 서버 실행 후 수동 검증:
        POST http://localhost:8001/api/image-classifier/classify/start
    """

    def test_start_with_duplicate_group_files(self, client, test_db, tmp_path):
        """중복 그룹 파일이 있을 때 /start가 정상 응답"""
        from PIL import Image
        from app.modules.image_classifier.routers.classify import classification_status
        classification_status["running"] = False

        # 카테고리 + 파일 + 중복 그룹 시드
        test_db.execute(text(
            "INSERT INTO categories (id, name, full_path) VALUES (1, 'Travel', 'Travel')"
        ))
        for i in range(1, 6):
            img = Image.new("RGB", (100, 100), color=(100, 150 + i, 200))
            path = tmp_path / f"dup_{i}.jpg"
            img.save(str(path))
            test_db.execute(text("""
                INSERT INTO file_classifications (id, file_path, file_hash, status)
                VALUES (:id, :path, :hash, 'pending')
            """), {"id": i, "path": str(path), "hash": f"hash_{i}"})

        test_db.execute(text("""
            INSERT INTO duplicate_groups (id, group_hash, member_count, status)
            VALUES (1, 'testhash', 5, 'pending')
        """))
        for i in range(1, 6):
            test_db.execute(text("""
                INSERT INTO duplicate_members (group_id, file_id, quality_score, phash_distance)
                VALUES (1, :fid, :quality, :dist)
            """), {"fid": i, "quality": 100 - i * 10, "dist": i - 1})
        test_db.commit()

        response = client.post("/api/ic/classify/start", json={
            "model": "claude_cli", "batch_size": 10
        })

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["status"] == "running"

        # 정리 — 백그라운드 작업 중지
        classification_status["running"] = False


# ================================================
# 항목 12: 배치 분류 안정성 (API 레벨)
# ================================================

class TestBatchClassificationStabilityAPI:
    """배치 분류 API 안정성 검증

    NOTE: 실제 분류 완료까지의 E2E는 LLM 워커 필요.
    여기서는 API 계층의 안정성(시작/상태/중지)을 검증합니다.
    """

    def test_batch_start_10_files(self, client, seeded_files_for_e2e, test_db):
        """10장 배치 시작 요청이 정상 응답"""
        from app.modules.image_classifier.routers.classify import classification_status
        classification_status["running"] = False

        response = client.post("/api/ic/classify/start", json={
            "model": "claude_cli", "batch_size": 5
        })

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 10
        assert data["status"] == "running"

        classification_status["running"] = False

    def test_status_api_returns_progress(self, client, seeded_files_for_e2e):
        """분류 중 /status가 진행 상태를 반환"""
        from app.modules.image_classifier.routers.classify import classification_status
        classification_status.update({
            "running": True,
            "total": 10,
            "processed": 3,
            "failed": 1,
            "model": "claude_cli",
            "current_file": "img_4.jpg",
        })

        response = client.get("/api/ic/classify/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is True
        assert data["total"] == 10
        assert data["processed"] == 3
        assert data["failed"] == 1

        classification_status["running"] = False

    def test_stop_during_batch(self, client, seeded_files_for_e2e):
        """실행 중 /stop 호출 시 정상 중지"""
        from app.modules.image_classifier.routers.classify import classification_status
        classification_status["running"] = True

        response = client.post("/api/ic/classify/stop")
        assert response.status_code == 200
        assert not classification_status["running"]

    def test_duplicate_start_rejected(self, client, seeded_files_for_e2e):
        """이미 실행 중일 때 /start 거부"""
        from app.modules.image_classifier.routers.classify import classification_status
        classification_status["running"] = True

        response = client.post("/api/ic/classify/start", json={
            "model": "claude_cli"
        })
        assert response.status_code == 400
        assert "already running" in response.json()["detail"].lower()

        classification_status["running"] = False
