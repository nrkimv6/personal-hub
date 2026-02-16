/**
 * API Client - 공통 request 함수 및 인증 처리
 */

// 브라우저 환경 체크
const isBrowser = typeof window !== 'undefined';

/**
 * API Base URL 결정
 * - Capacitor 네이티브 앱: 환경변수 또는 기본값 사용
 * - 웹(PWA): 상대경로 사용 (현재 도메인 기준)
 */
function getApiBase(): string {
  if (isBrowser && (window as any).Capacitor?.isNativePlatform()) {
    return import.meta.env.VITE_API_URL || 'https://dev-monitor.woory.day/api/v1';
  }
  return '/api/v1';
}

export const API_BASE = getApiBase();
const TOKEN_KEY = 'auth_token';

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
 * API 연결 에러 클래스 (좀비 포트 감지용)
 */
export class ApiConnectionError extends Error {
  constructor(message: string, public readonly originalError?: Error) {
    super(message);
    this.name = 'ApiConnectionError';
  }
}

/**
 * 기존 signal과 타임아웃 signal을 합치는 유틸리티
 * - 사용자의 AbortController signal과 타임아웃 signal을 모두 처리
 * - 둘 중 하나라도 abort되면 전체 요청이 중단됨
 */
function mergeSignals(
  existingSignal: AbortSignal | undefined,
  timeoutSignal: AbortSignal
): AbortSignal {
  if (!existingSignal) return timeoutSignal;

  // AbortSignal.any() 지원 시 사용 (Chrome 116+, Firefox 124+, Safari 17.4+)
  if ('any' in AbortSignal) {
    return (AbortSignal as any).any([existingSignal, timeoutSignal]);
  }

  // 폴백: 수동 합성
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  existingSignal.addEventListener('abort', onAbort);
  timeoutSignal.addEventListener('abort', onAbort);
  return controller.signal;
}

/**
 * 타임아웃 기능이 있는 fetch 래퍼
 * - 기본 타임아웃: 30초
 * - 기존 AbortController signal과 충돌하지 않도록 signal 합성
 * - 타임아웃 시 명확한 에러 메시지 반환
 *
 * @param url - 요청 URL
 * @param options - fetch 옵션
 * @param timeout - 타임아웃 (밀리초), 기본값 30000ms (30초)
 * @returns fetch Response
 */
export async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeout: number = 30000
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  // 기존 signal이 있으면 합침 (AbortController signal 충돌 방지)
  const mergedSignal = mergeSignals(options.signal, controller.signal);

  try {
    const response = await fetch(url, {
      ...options,
      signal: mergedSignal
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === 'AbortError') {
      // 사용자 abort vs 타임아웃 구분
      if (options.signal?.aborted) {
        throw error; // 사용자가 직접 abort한 경우 원래 에러 전달
      }
      throw new Error(`요청 타임아웃 (${timeout}ms): ${url}`);
    }
    throw error;
  }
}

/**
 * 글로벌 API 에러 핸들러 (타임아웃, 연결 에러 등 자동 알림용)
 * - 레이아웃에서 toast store와 연결하여 사용
 */
type ApiErrorHandler = (message: string, type: 'timeout' | 'connection' | 'auth') => void;
let globalErrorHandler: ApiErrorHandler | null = null;

export function setApiErrorHandler(handler: ApiErrorHandler): void {
  globalErrorHandler = handler;
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
  let response: Response;
  try {
    response = await fetchWithTimeout(url, { ...options, headers, credentials: 'include' });
  } catch (err) {
    const error = err instanceof Error ? err : new Error(String(err));
    // 타임아웃 에러 감지
    if (error.message.includes('타임아웃')) {
      globalErrorHandler?.(error.message, 'timeout');
      throw error;
    }
    // 네트워크 에러 (API 서버 연결 불가 - 좀비 포트 가능성)
    const connError = new ApiConnectionError(
      'API 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.',
      error
    );
    globalErrorHandler?.(connError.message, 'connection');
    throw connError;
  }

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
