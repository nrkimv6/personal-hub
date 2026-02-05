"""
Uvicorn 서버 인스턴스 공유 모듈.

프로그래밍 방식 uvicorn 실행 시 서버 참조를 저장하여
self-restart 등에서 server.should_exit = True 로 graceful shutdown을 트리거합니다.

CLI uvicorn (python -m uvicorn) 실행 시에는 서버 참조가 None이며,
이 경우 signal.raise_signal(signal.SIGINT) fallback을 사용합니다.
"""

_uvicorn_server = None


def set_server(server):
    """uvicorn.Server 인스턴스를 저장합니다."""
    global _uvicorn_server
    _uvicorn_server = server


def get_server():
    """저장된 uvicorn.Server 인스턴스를 반환합니다. 없으면 None."""
    return _uvicorn_server
