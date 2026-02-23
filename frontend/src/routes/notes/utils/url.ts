/**
 * URL 유틸리티 함수 모음
 * - extractUrls: 텍스트에서 URL 배열 추출
 * - getDomain: URL에서 도메인명 추출
 * - linkifyText: 텍스트 내 URL을 클릭 가능한 링크로 변환
 */

const URL_REGEX = /https?:\/\/[^\s<>"{}|\\^[\]`]+/g;

/**
 * 텍스트에서 URL 배열을 추출합니다.
 */
export function extractUrls(text: string): string[] {
  if (!text) return [];
  return text.match(URL_REGEX) ?? [];
}

/**
 * URL에서 호스트명(도메인)을 반환합니다.
 * 파싱 실패 시 원본 URL을 반환합니다.
 */
export function getDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

/**
 * 텍스트 내 URL을 `<a href="..." target="_blank" rel="noopener noreferrer">도메인</a>` 으로 변환합니다.
 * XSS 방지를 위해 URL은 인코딩됩니다.
 */
export function linkifyText(text: string): string {
  if (!text) return '';
  return text.replace(URL_REGEX, (url) => {
    const domain = getDomain(url);
    const encodedUrl = encodeURI(url);
    return `<a href="${encodedUrl}" target="_blank" rel="noopener noreferrer">${domain}</a>`;
  });
}
