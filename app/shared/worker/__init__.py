"""
Worker 공통 모듈

워커 클래스들이 공유하는 기본 기능을 제공합니다.

모듈 구조:
- base_worker.py: 워커 기본 클래스 (추상)
"""

from .base_worker import BaseWorker

__all__ = [
    'BaseWorker',
]
