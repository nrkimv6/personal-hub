"""dev-runner-command-listener 노이즈 필터 유틸

gemini CLI가 백그라운드 실행 시 발생하는 노이즈 출력을
Redis publish 전에 억제합니다. 파일 기록은 유지.

억제 대상:
  - xterm.js: Parsing error: {...}  — gemini 내부 xterm.js 파싱 오류 JSON 블롭
  - Error: AttachConsole failed 스택트레이스  — node-pty 콘솔 세션 없음 오류
"""

# Redis publish에서 억제할 노이즈 블록 시작 패턴
NOISE_BLOCK_MARKERS = (
    "xterm.js: Parsing error:",
    "xterm.js:",
    "node_modules\\@lydell\\node-pty\\conpty_console_list_agent",
    "Error: AttachConsole failed",
    "    at Object.<anonymous>",
    "    at Module._compile",
    "    at Object..js",
    "    at Module.load",
    "    at Module._load",
    "    at TracingChannel",
    "    at wrapModuleLoad",
    "    at Module.executeUserEntryPoint",
    "    at node:internal",
    "    at node:diagnostics_channel",
    "Node.js v",
)


def is_noise_line(stripped: str) -> bool:
    """Redis publish를 억제할 노이즈 라인 여부 판별"""
    return stripped.startswith(NOISE_BLOCK_MARKERS)
