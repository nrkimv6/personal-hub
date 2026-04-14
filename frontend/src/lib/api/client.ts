/**
 * API Client - 공통 request 함수 및 인증 처리
 */

import { apiHealth } from '../stores/apiHealth.svelte';
import { classifyRequestFailure } from './requestFailure.js';

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
  const mergedSignal = mergeSignals(options.signal ?? undefined, controller.signal);

  try {
    const response = await fetch(url, {
      ...options,
      signal: mergedSignal
    });
    clearTimeout(timeoutId);
    apiHealth.reportConnectionSuccess();
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (isAbortError(error)) {
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
 * 401 Unauthorized 콜백 (페이지 reload 대신 사용)
 * - 순환 의존성 방지를 위해 콜백 패턴 사용 (auth.ts → client.ts → auth.ts 불가)
 * - 레이아웃에서 authStore.reset() + toast 알림으로 등록
 */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

// 중복 401 처리 방지 (폴링 다수가 동시에 401 받을 때 토스트 폭탄 방지)
let isHandling401 = false;

/**
 * API 요청 함수
 */
export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;

  // 401 처리 중이면 불필요한 폴링 API 호출 차단 (토스트 폭탄 및 반복 401 방지)
  if (isHandling401) {
    throw new Error('인증이 만료되었습니다');
  }

  // disconnected/reconnecting 상태에서 API 호출 차단 (/ready 엔드포인트는 예외 — 폴링이 차단되지 않도록)
  if (
    (apiHealth.state === 'disconnected' || apiHealth.state === 'reconnecting') &&
    !endpoint.endsWith('/ready')
  ) {
    throw new ApiConnectionError('서버 재연결 대기 중');
  }

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
    const failure = classifyRequestFailure(err, url);
    if (failure.kind === 'abort') {
      throw failure.error;
    }
    if (failure.kind === 'timeout') {
      globalErrorHandler?.(failure.error.message, 'timeout');
      throw failure.error;
    }
    // 네트워크 에러 (API 서버 연결 불가 - 좀비 포트 가능성)
    const connError = new ApiConnectionError(failure.message, failure.error);
    apiHealth.reportConnectionError();
    globalErrorHandler?.(connError.message, 'connection');
    throw connError;
  }

  // 401 Unauthorized 처리
  if (response.status === 401) {
    if (isBrowser && token) {
      localStorage.removeItem(TOKEN_KEY);
      // 중복 401 처리 방지 (3초 쿨다운)
      if (!isHandling401) {
        isHandling401 = true;
        setTimeout(() => { isHandling401 = false; }, 3000);
        globalErrorHandler?.('인증이 만료되었습니다. 재로그인이 필요합니다.', 'auth');
        onUnauthorized?.();
        window.dispatchEvent(new CustomEvent('auth-expired'));
      }
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
