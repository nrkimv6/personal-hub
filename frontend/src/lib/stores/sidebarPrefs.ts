/**
 * Sidebar Preferences Store
 *
 * - hiddenItems: 개별 숨김 처리된 nav item ID 목록 (localStorage)
 * - collapsedCategories: 접힌 카테고리 목록 (localStorage)
 */
import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const HIDDEN_ITEMS_KEY = 'sidebar-hidden-items';
const COLLAPSED_CATS_KEY = 'sidebar-collapsed-categories';

function load<T>(key: string, fallback: T): T {
	if (!browser) return fallback;
	try {
		const v = localStorage.getItem(key);
		return v ? JSON.parse(v) : fallback;
	} catch {
		return fallback;
	}
}

function save(key: string, value: unknown) {
	if (!browser) return;
	try {
		localStorage.setItem(key, JSON.stringify(value));
	} catch {}
}

function createHiddenItems() {
	const { subscribe, update, set } = writable<string[]>(load(HIDDEN_ITEMS_KEY, []));

	return {
		subscribe,
		toggle(id: string) {
			update((items) => {
				const next = items.includes(id) ? items.filter((i) => i !== id) : [...items, id];
				save(HIDDEN_ITEMS_KEY, next);
				return next;
			});
		},
		reset() {
			set([]);
			save(HIDDEN_ITEMS_KEY, []);
		}
	};
}

function createCollapsedCategories() {
	const { subscribe, update } = writable<string[]>(load(COLLAPSED_CATS_KEY, []));

	return {
		subscribe,
		toggle(cat: string) {
			update((cats) => {
				const next = cats.includes(cat) ? cats.filter((c) => c !== cat) : [...cats, cat];
				save(COLLAPSED_CATS_KEY, next);
				return next;
			});
		}
	};
}

export const hiddenItems = createHiddenItems();
export const collapsedCategories = createCollapsedCategories();
