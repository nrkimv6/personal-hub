"""
파일 검색 프리셋 정의

자주 사용하는 검색 범위를 미리 정의합니다.
경로는 Windows 절대경로 기준이며, 실제 환경에 맞게 수정 가능합니다.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class Preset:
    id: str
    name: str
    icon: str
    paths: List[str]
    extensions: List[str]
    excludes: List[str]


PRESETS: dict[str, Preset] = {
    "documents": Preset(
        id="documents",
        name="문서 전체",
        icon="📄",
        paths=[],  # 전체 디스크
        extensions=["doc", "docx", "pdf", "txt", "md", "hwp", "xlsx", "pptx"],
        excludes=[],
    ),
    "python_backend": Preset(
        id="python_backend",
        name="백엔드 (Python)",
        icon="🐍",
        paths=[r"D:\work\project"],
        extensions=["py", "pyi", "toml", "cfg", "ini", "yaml", "yml"],
        excludes=["__pycache__", ".venv", "dist", ".egg-info", "*.pyc", "*.pyo"],
    ),
    "frontend": Preset(
        id="frontend",
        name="프론트엔드 (React/Svelte)",
        icon="⚛️",
        paths=[r"D:\work\project"],
        extensions=["ts", "tsx", "js", "jsx", "svelte", "vue", "css", "scss", "html"],
        excludes=["node_modules", "dist", ".svelte-kit", "build", ".next"],
    ),
    "obsidian": Preset(
        id="obsidian",
        name="옵시디언",
        icon="📝",
        paths=[r"D:\Data\obsidian2"],
        extensions=["md"],
        excludes=[".obsidian", ".trash"],
    ),
    "downloads": Preset(
        id="downloads",
        name="다운로드",
        icon="📥",
        paths=[r"C:\Users\Narang\Downloads"],
        extensions=[],  # 전체
        excludes=[],
    ),
    "code_all": Preset(
        id="code_all",
        name="코드 전체",
        icon="💻",
        paths=[r"D:\work\project"],
        extensions=[
            "py", "ts", "tsx", "js", "jsx", "svelte", "vue",
            "css", "html", "yaml", "yml", "json", "sql", "sh", "ps1",
        ],
        excludes=[
            "node_modules", "__pycache__", "dist", ".venv", "build",
            ".svelte-kit", ".next", ".egg-info",
        ],
    ),
}
