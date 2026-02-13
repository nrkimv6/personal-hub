"""AI 분류 어댑터 테스트"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter
    from app.modules.image_classifier.adapters.gemini_cli import GeminiCLIAdapter
    from app.modules.image_classifier.adapters.base import ClassifyResult
    HAS_ADAPTERS = True
except ImportError:
    HAS_ADAPTERS = False

pytestmark = pytest.mark.skipif(
    not HAS_ADAPTERS,
    reason="adapters not available"
)


# ================================================
# Right: 기본 동작
# ================================================

@pytest.mark.asyncio
async def test_claude_is_available_success():
    """14.1 Right: is_available() → True (CLI 존재)"""
    adapter = ClaudeCLIAdapter(cli_path="mock_claude")

    # Mock subprocess
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.is_available()

    assert result is True


@pytest.mark.asyncio
async def test_claude_is_available_not_found():
    """14.2 Right: is_available() → False (CLI 없음)"""
    adapter = ClaudeCLIAdapter(cli_path="/nonexistent/claude")

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await adapter.is_available()

    assert result is False


@pytest.mark.asyncio
async def test_claude_classify_image_success():
    """14.3 Right: classify_image → ClassifyResult"""
    adapter = ClaudeCLIAdapter(cli_path="mock_claude")

    # Mock subprocess 응답
    mock_proc = AsyncMock()
    mock_response = {
        "category": "Travel/2023/04",
        "confidence": 0.92,
        "reasoning": "Beach photo"
    }
    mock_proc.communicate = AsyncMock(return_value=(
        json.dumps(mock_response).encode(),
        b""
    ))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.classify_image(
            image_path="/test/image.jpg",
            prompt="Classify this image",
            categories=["Travel", "Work"]
        )

    assert isinstance(result, ClassifyResult)
    assert result.category_path == "Travel/2023/04"
    assert result.confidence == 0.92
    assert result.reasoning == "Beach photo"
    assert "CLI" in result.model


@pytest.mark.asyncio
async def test_claude_classify_batch_success():
    """14.4 Right: classify_images_batch → 배열 응답"""
    adapter = ClaudeCLIAdapter(cli_path="mock_claude")

    # Mock subprocess 응답 (배열)
    mock_proc = AsyncMock()
    mock_response = [
        {
            "image_path": "/test/img1.jpg",
            "category": "Travel",
            "confidence": 0.9,
            "reasoning": "Beach"
        },
        {
            "image_path": "/test/img2.jpg",
            "category": "Work",
            "confidence": 0.85,
            "reasoning": "Office"
        }
    ]
    mock_proc.communicate = AsyncMock(return_value=(
        json.dumps(mock_response).encode(),
        b""
    ))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        results = await adapter.classify_images_batch(
            image_paths=["/test/img1.jpg", "/test/img2.jpg"],
            prompt="Classify",
            categories=["Travel", "Work"]
        )

    assert len(results) == 2
    assert results[0].category_path == "Travel"
    assert results[1].category_path == "Work"


@pytest.mark.asyncio
async def test_gemini_classify_image_success():
    """14.5 Right: Gemini classify_image 성공"""
    adapter = GeminiCLIAdapter(cli_path="mock_gemini")

    # Mock subprocess
    mock_proc = AsyncMock()
    mock_response = {
        "category": "Photos/2023",
        "confidence": 0.88,
        "reasoning": "Family photo"
    }
    mock_proc.communicate = AsyncMock(return_value=(
        json.dumps(mock_response).encode(),
        b""
    ))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.classify_image(
            image_path="/test/family.jpg",
            prompt="Classify",
            categories=["Photos", "Work"]
        )

    assert result.category_path == "Photos/2023"
    assert result.confidence == 0.88


@pytest.mark.asyncio
async def test_gemini_batch_sequential():
    """14.6 Right: Gemini batch는 순차 실행"""
    adapter = GeminiCLIAdapter(cli_path="mock_gemini")

    # Mock classify_image (각 호출마다 다른 결과 반환)
    call_count = 0

    async def mock_classify(image_path, prompt, categories):
        nonlocal call_count
        call_count += 1
        return ClassifyResult(
            category_path=f"Category{call_count}",
            confidence=0.8,
            reasoning=f"Call {call_count}",
            model="gemini"
        )

    adapter.classify_image = mock_classify

    results = await adapter.classify_images_batch(
        image_paths=["/test/img1.jpg", "/test/img2.jpg", "/test/img3.jpg"],
        prompt="Classify",
        categories=["Cat1", "Cat2"]
    )

    # 순차 실행되어 3개 결과
    assert len(results) == 3
    assert results[0].category_path == "Category1"
    assert results[2].category_path == "Category3"


# ================================================
# Boundary: 경계 조건
# ================================================

@pytest.mark.asyncio
async def test_timeout_handling():
    """14.7 Boundary: timeout → error/timeout"""
    adapter = ClaudeCLIAdapter(cli_path="mock_claude")
    adapter.timeout = 0.1  # 매우 짧은 타임아웃

    # Mock subprocess (지연 응답)
    async def delayed_communicate():
        await asyncio.sleep(1)  # timeout보다 김
        return (b"", b"")

    mock_proc = AsyncMock()
    mock_proc.communicate = delayed_communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.classify_image(
            image_path="/test/image.jpg",
            prompt="Classify",
            categories=["Cat1"]
        )

    # timeout 시 error 카테고리
    assert result.category_path == "error/timeout"
    assert result.confidence == 0.0


# ================================================
# Error: 예외 처리
# ================================================

@pytest.mark.asyncio
async def test_cli_error_nonzero_returncode():
    """14.8 Error: CLI 오류 (returncode != 0)"""
    adapter = ClaudeCLIAdapter(cli_path="mock_claude")

    # Mock subprocess (에러 반환)
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(
        b"",
        b"CLI Error: Invalid arguments"
    ))
    mock_proc.returncode = 1  # 에러

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.classify_image(
            image_path="/test/image.jpg",
            prompt="Classify",
            categories=["Cat1"]
        )

    # 에러 처리
    assert result.category_path == "error/exception"
    assert result.confidence == 0.0
    assert "CLI 오류" in result.reasoning


@pytest.mark.asyncio
async def test_json_parse_error():
    """14.9 Error: JSON 파싱 오류 → error/exception"""
    adapter = ClaudeCLIAdapter(cli_path="mock_claude")

    # Mock subprocess (잘못된 JSON)
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(
        b"invalid json{",
        b""
    ))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await adapter.classify_image(
            image_path="/test/image.jpg",
            prompt="Classify",
            categories=["Cat1"]
        )

    # JSON 파싱 실패 → error
    assert result.category_path == "error/exception"
    assert result.confidence == 0.0


# ================================================
# Inverse: prompt 생성
# ================================================

def test_prompt_building():
    """14.10 Inverse: _build_prompt 형식 확인"""
    adapter = ClaudeCLIAdapter()

    prompt = adapter._build_prompt(
        context="Classify family photos",
        categories=["Travel", "Work", "Family"],
        image_paths=["/test/img1.jpg", "/test/img2.jpg"]
    )

    # 프롬프트에 필수 요소 포함 확인
    assert "Classify family photos" in prompt
    assert "Travel" in prompt
    assert "Work" in prompt
    assert "Family" in prompt
    assert "/test/img1.jpg" in prompt
    assert "/test/img2.jpg" in prompt
