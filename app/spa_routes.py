"""
SPA(Single Page Application) 정적 파일 및 프론트엔드 라우트 등록 모듈.
Admin 모드에서는 dev 서버가 프론트엔드를 담당하므로 등록하지 않습니다.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path


def register_spa_routes(app: FastAPI, app_mode: str) -> None:
    """정적 파일 마운트 및 SPA 프론트엔드 라우트를 등록합니다.

    Admin 모드에서는 dev 서버(6101)가 프론트엔드를 담당하므로
    API(8001)에서 stale static 파일을 서빙하지 않습니다.
    """
    if app_mode == "admin":
        return

    # 정적 에셋 마운트
    _app_static_dir = Path("app/static/_app")
    if _app_static_dir.exists():
        app.mount("/_app", StaticFiles(directory="app/static/_app"), name="app_assets")

    # SPA 라우팅을 위한 HTML 파일 제공
    @app.get("/")
    async def serve_index():
        return FileResponse("app/static/index.html")

    @app.get("/accounts")
    async def serve_accounts():
        return FileResponse("app/static/index.html")

    @app.get("/businesses")
    async def serve_businesses():
        return FileResponse("app/static/index.html")

    @app.get("/booking")
    async def serve_booking():
        return FileResponse("app/static/index.html")

    @app.get("/settings")
    async def serve_settings():
        return FileResponse("app/static/index.html")

    @app.get("/settings/{path:path}")
    async def serve_settings_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Instagram 라우트
    @app.get("/instagram")
    async def serve_instagram():
        return FileResponse("app/static/index.html")

    @app.get("/instagram/{path:path}")
    async def serve_instagram_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Auth 라우트 (프론트엔드 콜백 페이지)
    @app.get("/auth/callback")
    async def serve_auth_callback():
        return FileResponse("app/static/index.html")

    @app.get("/login")
    async def serve_login():
        return FileResponse("app/static/index.html")

    # Events 라우트
    @app.get("/events")
    async def serve_events():
        return FileResponse("app/static/index.html")

    @app.get("/events/{path:path}")
    async def serve_events_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Google 검색 라우트
    @app.get("/google")
    async def serve_google():
        return FileResponse("app/static/index.html")

    @app.get("/google/{path:path}")
    async def serve_google_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Writing 라우트
    @app.get("/writing")
    async def serve_writing():
        return FileResponse("app/static/index.html")

    @app.get("/writing/{path:path}")
    async def serve_writing_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Notes 라우트 (메모 CRUD)
    @app.get("/notes")
    async def serve_notes():
        return FileResponse("app/static/index.html")

    @app.get("/notes/{path:path}")
    async def serve_notes_subpages(path: str):
        return FileResponse("app/static/index.html")

    # 통합 크롤링 라우트
    @app.get("/crawl")
    async def serve_crawl():
        return FileResponse("app/static/index.html")

    @app.get("/crawl/{path:path}")
    async def serve_crawl_subpages(path: str):
        return FileResponse("app/static/index.html")

    # 태스크 스케줄 라우트
    @app.get("/tasks")
    async def serve_tasks():
        return FileResponse("app/static/index.html")

    @app.get("/tasks/{path:path}")
    async def serve_tasks_subpages(path: str):
        return FileResponse("app/static/index.html")

    @app.get("/video-downloads")
    async def serve_video_downloads():
        return FileResponse("app/static/index.html")

    @app.get("/video-downloads/{path:path}")
    async def serve_video_downloads_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Activity (문화/체육센터) 라우트
    @app.get("/activity")
    async def serve_activity():
        return FileResponse("app/static/index.html")

    @app.get("/activity/{path:path}")
    async def serve_activity_subpages(path: str):
        return FileResponse("app/static/index.html")

    # System (서비스 대시보드) 라우트
    @app.get("/system")
    async def serve_system():
        return FileResponse("app/static/index.html")

    @app.get("/system/{path:path}")
    async def serve_system_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Mobile (모바일 크롤링) 라우트
    @app.get("/mobile")
    async def serve_mobile():
        return FileResponse("app/static/index.html")

    @app.get("/mobile/{path:path}")
    async def serve_mobile_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Dev Runner 라우트
    @app.get("/dev-runner")
    async def serve_dev_runner():
        return FileResponse("app/static/index.html")

    @app.get("/dev-runner/{path:path}")
    async def serve_dev_runner_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Classify (Image Classifier) 라우트
    @app.get("/classify")
    async def serve_classify():
        return FileResponse("app/static/index.html")

    @app.get("/classify/{path:path}")
    async def serve_classify_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Git Repository Manager 라우트
    @app.get("/git-repos")
    async def serve_git_repos():
        return FileResponse("app/static/index.html")

    @app.get("/git-repos/{path:path}")
    async def serve_git_repos_subpages(path: str):
        return FileResponse("app/static/index.html")

    # Plans (계획서 관리) 라우트
    @app.get("/plans")
    async def serve_plans():
        return FileResponse("app/static/index.html")

    @app.get("/plans/{path:path}")
    async def serve_plans_subpages(path: str):
        return FileResponse("app/static/index.html")

    # 쿠팡 라우트
    @app.get("/coupang")
    async def serve_coupang():
        return FileResponse("app/static/index.html")

    @app.get("/coupang/{path:path}")
    async def serve_coupang_subpages(path: str):
        return FileResponse("app/static/index.html")
