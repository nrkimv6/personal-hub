"""
AI 분류 어댑터 기본 인터페이스
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClassifyRequest:
    """AI 분류 요청"""
    image_paths: list[str]  # 이미지 파일 경로 목록
    prompt: str  # AI에게 전달할 프롬프트
    categories: list[str]  # 가능한 카테고리 목록


@dataclass
class ClassifyResult:
    """AI 분류 결과"""
    category_path: str  # "outdoor/travel" 형식의 카테고리 경로
    confidence: float  # 0.0 ~ 1.0
    reasoning: Optional[str] = None  # AI가 제공한 분류 이유
    model: Optional[str] = None  # 사용한 모델명


class ClassifierAdapter(ABC):
    """AI 분류 어댑터 기본 클래스"""

    @abstractmethod
    async def classify_image(
        self,
        image_path: str,
        prompt: str,
        categories: list[str],
    ) -> ClassifyResult:
        """
        단일 이미지 분류

        Args:
            image_path: 이미지 파일 절대 경로
            prompt: AI에게 전달할 프롬프트 (컨텍스트 포함)
            categories: 가능한 카테고리 목록

        Returns:
            ClassifyResult 객체
        """
        pass

    @abstractmethod
    async def classify_images_batch(
        self,
        image_paths: list[str],
        prompt: str,
        categories: list[str],
    ) -> list[ClassifyResult]:
        """
        이미지 배치 분류 (클러스터 단위)

        Args:
            image_paths: 이미지 파일 경로 목록
            prompt: AI에게 전달할 프롬프트
            categories: 가능한 카테고리 목록

        Returns:
            ClassifyResult 목록 (입력 순서 유지)
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """사용 중인 모델명 반환"""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """어댑터 사용 가능 여부 확인 (CLI 실행 가능, API 키 유효 등)"""
        pass
