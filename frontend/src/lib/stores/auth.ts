/**
 * 인증 상태 관리 스토어
 *
 * Google OAuth 인증 후 JWT 토큰 관리
 */

import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';
import { fetchWithTimeout } from '$lib/api/client';

const API_BASE = '/api/v1';
const TOKEN_KEY = 'auth_token';

export interface AuthState {
	isLoggedIn: boolean;
	isAdmin: boolean;
	email: string | null;
	isLoading: boolean;
	isExpired: boolean;
}

// 초기 상태
const initialState: AuthState = {
	isLoggedIn: false,
	isAdmin: false,
	email: null,
	isLoading: true,
	isExpired: false
};

// 스토어 생성
function createAuthStore() {
	const { subscribe, set, update } = writable<AuthState>(initialState);

	return {
		subscribe,

		/**
		 * 인증 상태 확인
		 *
		 * localhost에서는 토큰 없이도 자동 관리자 처리
		 * Cookie fallback: localStorage 토큰이 없어도 Cookie로 인증 가능
		 */
		async checkAuth(): Promise<void> {
			if (!browser) return;

			// localhost 체크 - 프론트엔드에서도 직접 확인
			const isLocalhost = window.location.hostname === 'localhost' ||
				window.location.hostname === '127.0.0.1' ||
				window.location.hostname === '::1';
			const isPublicPreview = isLocalhost && window.location.port === '6100';
			const shouldAutoAdmin = isLocalhost && !isPublicPreview;

			const token = localStorage.getItem(TOKEN_KEY);

			try {
				const headers: HeadersInit = {};
				if (token) {
					headers.Authorization = `Bearer ${token}`;
				}

				// credentials: 'include'로 Cookie도 전송 (PWA 공유 기능 등)
				// 백엔드는 Authorization 헤더가 없으면 Cookie에서 토큰 확인
				const response = await fetchWithTimeout(`${API_BASE}/auth/me`, { headers, credentials: 'include' }, 10000);

				// 401 Unauthorized: 토큰이 유효하지 않음 (만료 등)
				if (response.status === 401) {
					if (token) {
						localStorage.removeItem(TOKEN_KEY);
					}
					set({ ...initialState, isLoading: false });
					return;
				}

				// 다른 HTTP 오류는 네트워크 문제로 간주 - 토큰 유지
				if (!response.ok) {
					console.warn('[auth] API error, keeping token:', response.status);
					set({ ...initialState, isLoading: false });
					return;
				}

				const data = await response.json();

				if (isPublicPreview) {
					// public PREVIEW(6100)는 관리자 오토 판정을 사용하지 않는다.
					set({ ...initialState, isLoading: false });
				} else if (data.user) {
					set({
						isLoggedIn: true,
						isAdmin: data.user.isAdmin,
						email: data.user.email,
						isLoading: false,
						isExpired: false
					});
				} else if (shouldAutoAdmin) {
					// 백엔드가 user를 반환하지 않아도 localhost면 관리자 처리
					set({
						isLoggedIn: true,
						isAdmin: true,
						email: 'localhost@admin',
						isLoading: false,
						isExpired: false
					});
				} else {
					// 비로그인 상태 (토큰도 없고 Cookie도 없음)
					// 토큰은 삭제하지 않음 - 백엔드가 이미 확인함
					set({ ...initialState, isLoading: false });
				}
			} catch (error) {
				// 네트워크 오류 시 토큰 삭제하지 않음 (일시적 오류 가능성)
				console.warn('[auth] Network error, keeping token:', error);

				// 에러 시에도 localhost면 관리자 처리
				if (shouldAutoAdmin) {
					set({
						isLoggedIn: true,
						isAdmin: true,
						email: 'localhost@admin',
						isLoading: false,
						isExpired: false
					});
				} else {
					// 토큰 삭제하지 않음 - 다음 요청에서 재시도
					set({ ...initialState, isLoading: false });
				}
			}
		},

		/**
		 * Google OAuth 로그인 시작
		 */
		login(): void {
			if (!browser) return;
			window.location.href = `${API_BASE}/auth/login`;
		},

		/**
		 * OAuth 콜백에서 토큰 설정
		 */
		setToken(token: string): void {
			if (!browser) return;
			localStorage.setItem(TOKEN_KEY, token);
		},

		/**
		 * 현재 토큰 반환
		 */
		getToken(): string | null {
			if (!browser) return null;
			return localStorage.getItem(TOKEN_KEY);
		},

		/**
		 * 로그아웃
		 */
		async logout(): Promise<void> {
			if (!browser) return;

			try {
				const token = localStorage.getItem(TOKEN_KEY);
				await fetchWithTimeout(`${API_BASE}/auth/logout`, {
					method: 'POST',
					headers: token ? { Authorization: `Bearer ${token}` } : {},
					credentials: 'include'  // Cookie 삭제를 위해
				});
			} catch {
				// 로그아웃 API 실패해도 클라이언트 측은 처리
			}

			localStorage.removeItem(TOKEN_KEY);
			set({ ...initialState, isLoading: false });
		},

		/**
		 * 상태 초기화
		 */
		reset(): void {
			set({ ...initialState, isLoading: false });
		},

		/**
		 * 토큰 만료 처리 (401 응답 시 호출)
		 * reset()과 동일하나 isExpired: true로 배너 표시
		 */
		expire(): void {
			set({ ...initialState, isLoading: false, isExpired: true });
		}
	};
}

export const authStore = createAuthStore();

// 편의를 위한 derived stores
export const isLoggedIn = derived(authStore, ($auth) => $auth.isLoggedIn);
export const isAdmin = derived(authStore, ($auth) => $auth.isAdmin);
export const userEmail = derived(authStore, ($auth) => $auth.email);
export const isAuthLoading = derived(authStore, ($auth) => $auth.isLoading);
