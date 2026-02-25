"""dev-runner-command-listener 노이즔 필터 유틸

gemini CLI가 백그라운드 실행 시 발생하는 노이즈 출력을
Redis publish 전에 억제합니다.

억제 대상:
  - xterm.js: Parsing error: {...}  — gemini 내부 xterm.js 파싱 오류 JSON 블롭 (멀티라인)
  - Error: AttachConsole failed 스택트레이스  — node-pty 콘솔 세션 없음 오류
"""
import re

# 블록 시작 패턴 (이 줄 이후 JSON 닫힘까지 전체 억제)
_BLOCK_START = (
    "xterm.js:",
)

# 단일 줄 노이즈 패턴
_SINGLE_NOISE = (
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

# 하위 호환: 기존 코드가 NOISE_BLOCK_MARKERS를 참조하는 경우
NOISE_BLOCK_MARKERS = _BLOCK_START + _SINGLE_NOISE

_STDERR_PREFIX_RE = re.compile(r'^\s*\[\d{2}:\d{2}:\d{2}\]\s*\[STDERR\]')


def _extract_content(line: str) -> str:
    """'  [HH:MM:SS] [STDERR] <내용>' 에서 <내용> 부분만 추출. 접두사 없으면 원본 반환."""
    return _STDERR_PREFIX_RE.sub('', line)


_ALL_NOISE = _BLOCK_START + _SINGLE_NOISE
_ALL_NOISE_LSTRIPPED = tuple(m.lstrip() for m in _ALL_NOISE)


def is_noise_line(stripped: str) -> bool:
    """Redis publish를 억제할 노이즈 라인 여부 판별.

    executor.py가 '[HH:MM:SS] [STDERR] <원본>' 형태로 감싸서 출력하므로
    접두사 제거 후 원본 내용을 기준으로 판별한다.
    """
    content = _extract_content(stripped)

    # 공백 보존 체크 (4-space 들여쓰기 마커) + lstrip 체크 (공백 제거 후)
    if content.startswith(_ALL_NOISE) or content.lstrip().startswith(_ALL_NOISE_LSTRIPPED):
        return True

    # xterm.js JSON 바디 줄 — 블록 시작 없이도 도달할 수 있음
    if _is_xterm_json_body(content.lstrip()):
        return True

    return False


def _is_xterm_json_body(content: str) -> bool:
    """xterm.js Parsing error JSON 블롭의 바디 줄 여부 판별.

    특징:
      - 숫자/쉼표만으로 구성된 줄: '0, 0, 0, 0,'
      - 닫는 괄호/중괄호: '],' '},' ']' '}'
      - xterm 내부 속성명: '_rejectDigits:', '_subParams:', 'Int32Array(', 'Uint16Array('
      - 'params:', 'position:', 'code:', 'currentState:', 'collect:', 'abort:', 'length:'
        (단, 일반 로그와 겹치지 않도록 줄 전체가 짧고 단순한 경우만)
    """
    if not content:
        return False
    # 닫는 괄호/중괄호만 있는 줄
    if content in (']', '},', '}', '],', '};'):
        return True
    # xterm 고유 속성
    _XTERM_PROPS = (
        '_rejectDigits:', '_rejectSubDigits:', '_digitIsSub:',
        '_subParams:', '_subParamsLength:', '_subParamsIdx:',
        'Int32Array(', 'Uint16Array(',
        'maxLength:', 'maxSubParamsLength:',
        'abort: false', 'abort: true',
        'currentState:', 'collect:',
        'length:', 'params:', 'position:', 'code:',
    )
    if content.startswith(_XTERM_PROPS):
        return True
    # 숫자/쉼표/공백만으로 구성된 줄 (배열 내부)
    if re.fullmatch(r'[\d,\s]+', content):
        return True
    return False
