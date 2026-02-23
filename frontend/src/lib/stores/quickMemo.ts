/**
 * Quick Memo Store
 * 전역 키보드 단축키(Ctrl+Shift+N)로 빠른 메모 생성 팝업 상태 관리
 */
import { writable } from 'svelte/store';
import { navEntries, isNavGroup, isActive } from '$lib/navigation';
import type { NavSingleItem } from '$lib/navigation';

// ============================================================
// Types
// ============================================================

export interface QuickMemoState {
	open: boolean;
	linkedMenuId: string | null;
	linkedMenuLabel: string | null;
	linkedTab: string | null;
}

// ============================================================
// Store
// ============================================================

const initialState: QuickMemoState = {
	open: false,
	linkedMenuId: null,
	linkedMenuLabel: null,
	linkedTab: null
};

export const quickMemo = writable<QuickMemoState>(initialState);

// ============================================================
// Actions
// ============================================================

export function openQuickMemo(
	menuId: string | null,
	menuLabel: string | null,
	tab: string | null
): void {
	quickMemo.set({
		open: true,
		linkedMenuId: menuId,
		linkedMenuLabel: menuLabel,
		linkedTab: tab
	});
}

export function closeQuickMemo(): void {
	quickMemo.update((state) => ({
		...state,
		open: false
	}));
}

// ============================================================
// Utils
// ============================================================

/**
 * 현재 pathname에 해당하는 메뉴를 navEntries에서 감지
 * navGroup은 제외하고 NavSingleItem만 순회
 */
export function detectCurrentMenu(pathname: string): { menuId: string; label: string } | null {
	for (const entry of navEntries) {
		if (isNavGroup(entry)) continue;
		const singleItem = entry as NavSingleItem;
		if (isActive(singleItem.href, pathname)) {
			return { menuId: singleItem.id, label: singleItem.label };
		}
	}
	return null;
}
