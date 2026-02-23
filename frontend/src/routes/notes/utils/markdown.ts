/**
 * 마크다운 렌더링 공통 유틸리티
 * NoteDetailModal과 NoteFormModal 미리보기에서 공유합니다.
 */

import { marked } from 'marked';
import hljs from 'highlight.js';
import DOMPurify from 'dompurify';

// marked 설정 (highlight.js 연동, GFM autolink 활성화) — 최초 1회 초기화
marked.setOptions({
  gfm: true,
  breaks: true,
  highlight: (code: string, lang: string) => {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value;
    }
    return hljs.highlightAuto(code).value;
  },
} as any);

/**
 * 마크다운 문자열을 안전한 HTML로 변환합니다.
 * XSS 방지를 위해 DOMPurify로 sanitize합니다.
 * target="_blank" 속성은 허용합니다 (외부 링크 새 탭 열기).
 */
export function renderMarkdown(content: string): string {
  if (!content) return '';
  const raw = marked.parse(content) as string;
  return DOMPurify.sanitize(raw, { ADD_ATTR: ['target'] });
}
