interface BackoffOptions {
	baseMs: number;
	maxMs: number;
	maxAttempts?: number;
}

export interface Backoff {
	readonly attempts: number;
	nextDelay(): number | null;
	reset(): void;
}

export function createBackoff({ baseMs, maxMs, maxAttempts }: BackoffOptions): Backoff {
	let attempts = 0;
	return {
		get attempts() {
			return attempts;
		},
		nextDelay() {
			if (maxAttempts !== undefined && attempts >= maxAttempts) return null;
			const delay = Math.min(baseMs * Math.pow(2, attempts), maxMs);
			attempts += 1;
			return delay;
		},
		reset() {
			attempts = 0;
		}
	};
}
