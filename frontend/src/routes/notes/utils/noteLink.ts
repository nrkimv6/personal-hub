/**
 * noteLink.ts — 메모 간 링크([[제목]]) 유틸리티
 *
 * - renderNoteLinks: 마크다운 렌더링 후 [[제목]] → <a> 태그 변환
 * - extractNoteLinkAtCursor: 커서 위치에서 [[ 뒤 텍스트 추출 (자동완성용)
 */

/**
 * HTML 내의 [[제목]] 패턴을 클릭 가능한 <a> 태그로 변환한다.
 * 마크다운 렌더링 후 적용해야 한다 (pre/code 내부는 이미 이스케이프됨).
 */
export function renderNoteLinks(html: string): string {
  return html.replace(
    /\[\[([^\]]+)\]\]/g,
    '<a class="note-link cursor-pointer text-purple-600 dark:text-purple-400 hover:underline" data-note-title="$1">$1</a>'
  );
}

/**
 * textarea의 커서 위치에서 [[ 뒤 텍스트를 추출한다.
 * [[ 이후 ]] 또는 줄바꿈이 없는 경우에만 추출.
 *
 * @returns { query, start, end } 또는 null (커서가 [[ 패턴 밖에 있을 때)
 */
export function extractNoteLinkAtCursor(
  text: string,
  cursorPos: number
): { query: string; start: number; end: number } | null {
  // 커서 이전 텍스트에서 마지막 [[ 위치를 찾는다
  const before = text.slice(0, cursorPos);
  const bracketIdx = before.lastIndexOf('[[');
  if (bracketIdx === -1) return null;

  // [[ 이후 현재까지 텍스트
  const between = before.slice(bracketIdx + 2);

  // ]] 또는 줄바꿈이 있으면 이미 닫힌 링크이거나 다른 줄 → null
  if (between.includes(']]') || between.includes('\n')) return null;

  return {
    query: between,
    start: bracketIdx,
    end: cursorPos,
  };
}
