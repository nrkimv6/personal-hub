/**
 * App Mode Store
 *
 * 앱 모드(production/development)를 관리하는 스토어.
 * - production: 조회 전용 (워커, 관리 기능 비활성화)
 * - development: 모든 기능 활성화
 */
import { writable, derived } from 'svelte/store';

export type AppMode = 'production' | 'development';

export interface AppModeState {
	mode: AppMode;
	isLoaded: boolean;
	features: {
		workers_enabled: boolean;
		admin_api_enabled: boolean;
		crawling_enabled: boolean;
		sniping_enabled: boolean;
	};
}

const initialState: AppModeState = {
	mode: 'production',
	isLoaded: false,
	features: {
		workers_enabled: false,
		admin_api_enabled: false,
		crawling_enabled: false,
		sniping_enabled: false
	}
};

export const appModeStore = writable<AppModeState>(initialState);

// Derived stores for convenience
export const appMode = derived(appModeStore, ($store) => $store.mode);
export const isDevMode = derived(appModeStore, ($store) => $store.mode === 'development');
export const isProductionMode = derived(appModeStore, ($store) => $store.mode === 'production');
export const appModeLoaded = derived(appModeStore, ($store) => $store.isLoaded);

/**
 * API에서 앱 모드를 로드합니다.
 */
export async function loadAppMode(): Promise<void> {
	try {
		const res = await fetch('/api/v1/system/mode');
		if (res.ok) {
			const data = await res.json();
			console.log('[appMode] API response:', data);
			appModeStore.set({
				mode: data.mode,
				isLoaded: true,
				features: data.features || initialState.features
			});
		} else {
			console.warn('[appMode] API failed:', res.status);
			// API 실패 시 production으로 기본 설정
			appModeStore.update((state) => ({ ...state, isLoaded: true }));
		}
	} catch (e) {
		console.error('[appMode] Network error:', e);
		// 네트워크 오류 시 production으로 기본 설정
		appModeStore.update((state) => ({ ...state, isLoaded: true }));
	}
}
