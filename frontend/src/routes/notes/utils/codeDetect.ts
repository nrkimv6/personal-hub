/**
 * 코드 감지 유틸리티
 * 붙여넣기 텍스트가 코드인지 판별하고 언어를 추측합니다.
 */

/**
 * 텍스트가 코드처럼 보이는지 판별합니다.
 * 오탐보다 미탐을 선호하는 보수적인 휴리스틱을 사용합니다.
 *
 * 조건 (2줄 이상 + 아래 중 하나 이상):
 * - 들여쓰기 된 줄이 50% 이상
 * - 세미콜론으로 끝나는 줄이 있음
 * - 중괄호 { } 또는 화살표 => 포함
 * - 코드 키워드 포함 (import/export/function/class/def/const/let/var/return/if/for)
 * - 셸 패턴 ($, #!)
 */
export function isCodeLike(text: string): boolean {
  const lines = text.split('\n').filter((l) => l.trim().length > 0);

  // 2줄 미만이면 코드 아님
  if (lines.length < 2) return false;

  // 들여쓰기 비율 확인
  const indentedLines = lines.filter((l) => /^[ \t]{2,}/.test(l));
  const indentRatio = indentedLines.length / lines.length;
  if (indentRatio >= 0.5) return true;

  const joined = text;

  // 세미콜론으로 끝나는 줄
  if (/;\s*$/m.test(joined)) return true;

  // 중괄호 또는 화살표
  if (/[{}]/.test(joined) || /=>/.test(joined)) return true;

  // 코드 키워드 패턴
  const codeKeywords =
    /\b(import|export|function|class|def |const |let |var |return |if\s*\(|for\s*\(|while\s*\(|async |await |public |private |protected |interface |type |enum )\b/;
  if (codeKeywords.test(joined)) return true;

  // 셸 패턴
  if (/^\s*\$\s+\w/.test(joined) || /^#!\//.test(joined)) return true;

  // SELECT/FROM SQL 패턴
  if (/\bSELECT\b.+\bFROM\b/is.test(joined)) return true;

  return false;
}

/**
 * 텍스트에서 프로그래밍 언어를 추측합니다.
 * 확신할 수 없으면 빈 문자열을 반환합니다.
 */
export function detectLanguage(text: string): string {
  // Python: def 또는 import ... from ... (Python 스타일)
  if (/\bdef\s+\w+\s*\(/.test(text)) return 'python';
  if (/^from\s+\S+\s+import\b/m.test(text)) return 'python';

  // Go
  if (/\bfunc\s+\w+/.test(text)) return 'go';
  if (/^package\s+\w+/m.test(text)) return 'go';

  // Rust
  if (/\bfn\s+\w+/.test(text)) return 'rust';
  if (/\blet\s+mut\b/.test(text)) return 'rust';

  // SQL
  if (/\bSELECT\b.+\bFROM\b/is.test(text)) return 'sql';
  if (/\b(INSERT INTO|UPDATE\s+\w+\s+SET|CREATE TABLE|DROP TABLE)\b/i.test(text)) return 'sql';

  // Shell/Bash
  if (/^#!\/.*sh\b/m.test(text)) return 'bash';
  if (/^\s*\$\s+\w/m.test(text)) return 'bash';
  if (/\b(echo|grep|awk|sed|curl|wget|chmod|sudo)\b/.test(text)) return 'bash';

  // TypeScript (const/let + => 또는 : type annotation)
  if (/\b(const|let)\s+\w+\s*:\s*\w+/.test(text)) return 'typescript';
  if (/\b(interface|type)\s+\w+\s*[={]/.test(text)) return 'typescript';
  if (/import\s+.*\s+from\s+['"]/.test(text) && /=>/.test(text)) return 'typescript';

  // JavaScript
  if (/\b(const|let|var)\s+\w+\s*=/.test(text) && !/:\s*\w+/.test(text)) return 'javascript';
  if (/\bfunction\s+\w+\s*\(/.test(text)) return 'javascript';

  // CSS
  if (/[.#][\w-]+\s*\{/.test(text)) return 'css';

  // HTML
  if (/<\w+[^>]*>/.test(text) && /<\/\w+>/.test(text)) return 'html';

  // JSON
  if (/^\s*[\[{]/.test(text.trim()) && /[\]}]\s*$/.test(text.trim())) {
    try {
      JSON.parse(text.trim());
      return 'json';
    } catch {
      // not valid JSON
    }
  }

  return '';
}
