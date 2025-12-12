"""
pytest 설정 및 공통 픽스처

Windows에서 한글 출력 시 인코딩 문제 해결을 위한 설정 포함
"""

import sys
import os

# Windows에서 UTF-8 인코딩 강제 설정
if sys.platform == 'win32':
    # stdout/stderr를 UTF-8로 설정
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    # 환경 변수 설정
    os.environ['PYTHONIOENCODING'] = 'utf-8'


import pytest
from pathlib import Path

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
