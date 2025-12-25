/**
 * Toast 알림 스토어
 */
import { writable } from 'svelte/store';

export interface Toast {
	id: number;
	message: string;
	type: 'success' | 'error' | 'info' | 'warning';
	duration?: number;
}

function createToastStore() {
	const { subscribe, update } = writable<Toast[]>([]);
	let nextId = 1;

	return {
		subscribe,
		show(message: string, type: Toast['type'] = 'info', duration = 3000) {
			const id = nextId++;
			const toast: Toast = { id, message, type, duration };

			update((toasts) => [...toasts, toast]);

			if (duration > 0) {
				setTimeout(() => {
					update((toasts) => toasts.filter((t) => t.id !== id));
				}, duration);
			}

			return id;
		},
		success(message: string, duration = 3000) {
			return this.show(message, 'success', duration);
		},
		error(message: string, duration = 5000) {
			return this.show(message, 'error', duration);
		},
		info(message: string, duration = 3000) {
			return this.show(message, 'info', duration);
		},
		warning(message: string, duration = 4000) {
			return this.show(message, 'warning', duration);
		},
		dismiss(id: number) {
			update((toasts) => toasts.filter((t) => t.id !== id));
		},
		clear() {
			update(() => []);
		}
	};
}

export const toast = createToastStore();
