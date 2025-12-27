/**
 * 인증 상태 관리 스토어
 *
 * Google OAuth 인증 후 JWT 토큰 관리
 */

import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';

const API_BASE = '/api/v1';
const TOKEN_KEY = 'auth_token';

export interface AuthState {
	isLoggedIn: boolean;
	isAdmin: boolean;
	email: string | null;
	isLoading: boolean;
}

// 초기 상태
const initialState: AuthState = {
	isLoggedIn: false,
	isAdmin: false,
	email: null,
	isLoading: true
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
		 */
		async checkAuth(): Promise<void> {
			if (!browser) return;

			// localhost 체크 - 프론트엔드에서도 직접 확인
			const isLocalhost = window.location.hostname === 'localhost' ||
				window.location.hostname === '127.0.0.1' ||
				window.location.hostname === '::1';

			const token = localStorage.getItem(TOKEN_KEY);

			try {
				const headers: HeadersInit = {};
				if (token) {
					headers.Authorization = `Bearer ${token}`;
				}

				// credentials: 'include'로 Cookie도 전송 (PWA 공유 기능 등)
				const response = await fetch(`${API_BASE}/auth/me`, { headers, credentials: 'include' });

				if (!response.ok) {
					throw new Error('인증 실패');
				}

				const data = await response.json();

				if (data.user) {
					set({
						isLoggedIn: true,
						isAdmin: data.user.isAdmin,
						email: data.user.email,
						isLoading: false
					});
				} else if (isLocalhost) {
					// 백엔드가 user를 반환하지 않아도 localhost면 관리자 처리
					set({
						isLoggedIn: true,
						isAdmin: true,
						email: 'localhost@admin',
						isLoading: false
					});
				} else {
					// 비로그인 상태
					if (token) {
						localStorage.removeItem(TOKEN_KEY);
					}
					set({ ...initialState, isLoading: false });
				}
			} catch {
				// 에러 시에도 localhost면 관리자 처리
				if (isLocalhost) {
					set({
						isLoggedIn: true,
						isAdmin: true,
						email: 'localhost@admin',
						isLoading: false
					});
				} else {
					if (token) {
						localStorage.removeItem(TOKEN_KEY);
					}
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
				await fetch(`${API_BASE}/auth/logout`, {
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
		}
	};
}

export const authStore = createAuthStore();

// 편의를 위한 derived stores
export const isLoggedIn = derived(authStore, ($auth) => $auth.isLoggedIn);
export const isAdmin = derived(authStore, ($auth) => $auth.isAdmin);
export const userEmail = derived(authStore, ($auth) => $auth.email);
export const isAuthLoading = derived(authStore, ($auth) => $auth.isLoading);
