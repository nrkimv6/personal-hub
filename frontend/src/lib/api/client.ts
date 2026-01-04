/**
 * API Client - 공통 request 함수 및 인증 처리
 */

export const API_BASE = '/api/v1';
const TOKEN_KEY = 'auth_token';

// 브라우저 환경 체크
const isBrowser = typeof window !== 'undefined';

/**
 * 저장된 인증 토큰 반환
 */
export function getAuthToken(): string | null {
  if (!isBrowser) return null;
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * 인증 토큰 저장
 */
export function setAuthToken(token: string): void {
  if (!isBrowser) return;
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * 인증 토큰 삭제
 */
export function clearAuthToken(): void {
  if (!isBrowser) return;
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * API 요청 함수
 */
export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;

  // 인증 헤더 추가
  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers
  };

  // credentials: 'include'로 Cookie 전송 (PWA 공유 기능 등에서 localStorage 접근 불가 시 대비)
  const response = await fetch(url, { ...options, headers, credentials: 'include' });

  // 401 Unauthorized 처리
  if (response.status === 401) {
    // 토큰이 유효하지 않으면 로컬스토리지에서 삭제
    if (isBrowser && token) {
      localStorage.removeItem(TOKEN_KEY);
      // 페이지 새로고침하여 인증 상태 갱신
      window.location.reload();
    }
    throw new Error('인증이 필요합니다');
  }

  // 403 Forbidden 처리
  if (response.status === 403) {
    throw new Error('권한이 없습니다');
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    // detail이 객체인 경우 message 추출, 문자열인 경우 그대로 사용
    const detail = error.detail;
    let message: string;
    if (typeof detail === 'object' && detail !== null) {
      message = detail.message || detail.code || JSON.stringify(detail);
    } else {
      message = detail || '요청 실패';
    }
    throw new Error(message);
  }

  // 204 No Content
  if (response.status === 204) {
    return null as T;
  }

  return response.json();
}
