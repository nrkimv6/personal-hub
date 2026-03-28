"""app.main import 테스트 — 분리 후 main 정상 import 검증."""
import os
import importlib


class TestMainModuleImportable:

    def test_main_module_importable(self):
        """TESTING=1 설정 후 app.main import 에러 없이 성공 (RIGHT)"""
        assert os.environ.get("TESTING") == "1"
        import app.main
        importlib.reload(app.main)

    def test_main_has_app_instance(self):
        """app.main에 FastAPI 인스턴스 app이 존재함 확인 (RIGHT)"""
        assert os.environ.get("TESTING") == "1"
        import app.main
        from fastapi import FastAPI
        assert hasattr(app.main, "app"), "app.main에 app 인스턴스가 없음"
        assert isinstance(app.main.app, FastAPI), "app.main.app이 FastAPI 인스턴스가 아님"

    def test_lifespan_import_in_main(self):
        """app.main이 app.lifespan에서 lifespan을 import함 확인 (RIGHT)"""
        assert os.environ.get("TESTING") == "1"
        import app.main
        assert app.main.app.router.lifespan_context is not None, "lifespan_context가 설정되지 않음"
