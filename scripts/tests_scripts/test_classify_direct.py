"""Claude CLI 직접 호출 테스트"""
import asyncio
import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.insert(0, r"D:\work\project\tools\monitor-page")

from app.modules.image_classifier.adapters.claude_cli import ClaudeCLIAdapter
from app.modules.image_classifier.config import settings

async def main():
    # 썸네일 있는 파일로 테스트
    thumb_dir = settings.THUMBNAIL_DIR
    thumbs = list(thumb_dir.glob("*.jpg"))[:1]
    if not thumbs:
        print("썸네일 없음!")
        return

    thumb = thumbs[0]
    print(f"테스트 이미지: {thumb} ({thumb.stat().st_size} bytes)")

    def on_output(line):
        print(f"  [stderr] {line[:120]}")

    adapter = ClaudeCLIAdapter(on_output=on_output)
    categories = ["사진/인물", "사진/풍경", "사진/음식", "사진/동물", "디자인/패턴", "문서/스크린샷", "기타"]

    print(f"\n분류 시작...")
    try:
        result = await adapter.classify_image(
            str(thumb),
            "이미지의 내용을 분석하여 가장 적합한 카테고리로 분류하세요.",
            categories
        )
        print(f"\n결과:")
        print(f"  category: {result.category_path}")
        print(f"  confidence: {result.confidence}")
        print(f"  reasoning: {result.reasoning}")
        print(f"  model: {result.model}")
    except Exception as e:
        print(f"에러: {type(e).__name__}: {e}")

asyncio.run(main())
