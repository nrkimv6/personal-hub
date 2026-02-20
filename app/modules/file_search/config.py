"""
파일 검색 모듈 설정

환경변수 또는 기본값으로 Everything / ripgrep 연동 설정을 관리합니다.
대용량 디렉토리 검색 시 RIPGREP_TIMEOUT을 늘려서 사용하세요.
"""
import os

# Everything HTTP 서버 설정
EVERYTHING_HOST: str = os.environ.get("EVERYTHING_HOST", "localhost")
EVERYTHING_PORT: int = int(os.environ.get("EVERYTHING_PORT", "7780"))

# ripgrep subprocess 타임아웃 (초)
# 대용량 디렉토리 검색 시 상향 가능 (예: RIPGREP_TIMEOUT=300)
RIPGREP_TIMEOUT: int = int(os.environ.get("RIPGREP_TIMEOUT", "120"))
