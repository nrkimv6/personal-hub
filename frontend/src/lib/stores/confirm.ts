import { writable } from 'svelte/store';

export type ConfirmVariant = 'default' | 'warning' | 'danger';

export interface ConfirmOptions {
	title?: string;
	message: string;
	confirmText?: string;
	cancelText?: string;
	variant?: ConfirmVariant;
}

export interface ConfirmRequest extends Required<ConfirmOptions> {
	id: number;
}

type PendingRequest = ConfirmRequest & {
	resolve: (confirmed: boolean) => void;
};

const { subscribe, set } = writable<ConfirmRequest | null>(null);

let nextId = 1;
let active: PendingRequest | null = null;
const queue: PendingRequest[] = [];

function normalizeOptions(input: string | ConfirmOptions): Required<ConfirmOptions> {
	if (typeof input === 'string') {
		return {
			title: '확인',
			message: input,
			confirmText: '확인',
			cancelText: '취소',
			variant: 'default',
		};
	}

	return {
		title: input.title ?? '확인',
		message: input.message,
		confirmText: input.confirmText ?? '확인',
		cancelText: input.cancelText ?? '취소',
		variant: input.variant ?? 'default',
	};
}

function publishNext() {
	active = queue.shift() ?? null;
	set(active ? { ...active } : null);
}

export const confirmState = { subscribe };

export function confirm(options: string | ConfirmOptions): Promise<boolean> {
	return new Promise((resolve) => {
		queue.push({
			id: nextId++,
			...normalizeOptions(options),
			resolve,
		});

		if (!active) publishNext();
	});
}

export function resolveConfirm(confirmed: boolean) {
	if (!active) return;
	const current = active;
	active = null;
	current.resolve(confirmed);
	publishNext();
}
