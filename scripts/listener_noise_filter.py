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
    """Redis publish를 억제할 노이즈 라인 여부 판별.

    plan-runner executor가 '[HH:MM:SS] [STDERR] <원본줄>' 형태로 감싸서
    출력할 수 있으므로, 접두사를 제거한 원본 내용도 함께 체크한다.
    """
    if stripped.startswith(NOISE_BLOCK_MARKERS):
        return True
    # '[timestamp] [STDERR] <내용>' 접두사 제거 후 재검사
    # 예: "  [20:03:37] [STDERR] xterm.js: Parsing error: {"
    # 예: "  [20:03:37] [STDERR]     at Object.<anonymous> ..."
    import re
    _content = re.sub(r'^\s*\[\d{2}:\d{2}:\d{2}\]\s*\[STDERR\]', '', stripped)
    if _content != stripped:
        # 접두사가 제거됨 — 원본 공백 포함(startswith)과 lstrip 후(공백 없는 마커) 둘 다 체크
        if _content.startswith(NOISE_BLOCK_MARKERS):
            return True
        if _content.lstrip().startswith(NOISE_BLOCK_MARKERS):
            return True
        # 공백 없는 버전 마커도 체크 (스택트레이스 "at "으로 시작하는 경우)
        _NOISE_LSTRIPPED = tuple(m.lstrip() for m in NOISE_BLOCK_MARKERS)
        if _content.lstrip().startswith(_NOISE_LSTRIPPED):
            return True
    return False
