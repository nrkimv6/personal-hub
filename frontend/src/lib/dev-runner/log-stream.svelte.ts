import { devRunnerLogApi } from '$lib/api';
import { apiGate } from '$lib/stores/apiGate.svelte';
import { createBackoff } from './backoff';
import type { EventLinePayload } from './log-types';

type LogViewerMode = 'standalone' | 'managed';

interface LogStreamOptions {
	runnerId: () => string;
	mode: () => LogViewerMode;
	running: () => boolean;
	isMerging: () => boolean;
	getSinceLine: () => number;
	shouldLoadRecentBeforeReconnect: () => boolean;
	loadRecent: () => Promise<void>;
	addLine: (text: EventLinePayload, isStale: boolean) => void;
	clearNoiseTimer: () => void;
	hasExitBanner: () => boolean;
	clearExitBanner: () => void;
	showCompleted: (reason: string) => void;
}

export class LogStream {
	connected = $state<'connected' | 'disconnected'>('disconnected');
	sseStarted = $state(false);
	consecutiveErrors = $state(0);
	redisAvailable = $state(false);

	private eventSource: EventSource | null = null;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private reconnectBackoff = createBackoff({ baseMs: 3000, maxMs: 60000 });

	constructor(private options: LogStreamOptions) {
		if (options.mode() === 'managed') {
			this.connected = 'connected';
			this.sseStarted = true;
		}
	}

	get reconnectCount(): number {
		return this.reconnectBackoff.attempts;
	}

	async start(): Promise<void> {
		if (this.options.mode() === 'standalone') {
			await this.connect();
			return;
		}
		this.connected = 'connected';
		this.sseStarted = true;
		await this.fetchStatus();
	}

	stop(): void {
		this.close();
		this.clearReconnectTimer();
		this.options.clearNoiseTimer();
	}

	async reconnect(): Promise<void> {
		this.reconnectBackoff.reset();
		if (this.options.shouldLoadRecentBeforeReconnect()) {
			await this.options.loadRecent();
		}
		await this.connect();
	}

	async reconnectForModeSwitch(message: string): Promise<void> {
		this.options.addLine(message, false);
		await this.connect();
	}

	async fetchStatus(): Promise<void> {
		try {
			const statusRes = await fetch('/api/v1/dev-runner/status');
			if (statusRes.ok) {
				const data = await statusRes.json();
				this.redisAvailable = data.redis_connected ?? false;
			} else {
				this.redisAvailable = false;
			}
		} catch {
			this.redisAvailable = false;
		}
	}

	complete(reason: string = 'completed'): void {
		this.options.showCompleted(reason);
		this.close();
		this.connected = 'disconnected';
	}

	private async connect(): Promise<void> {
		this.close();
		this.options.clearNoiseTimer();

		if (apiGate.state !== 'open') {
			this.connected = 'disconnected';
			this.redisAvailable = false;
			return;
		}

		await this.fetchStatus();

		const runnerId = this.options.runnerId();
		this.eventSource = this.options.isMerging()
			? devRunnerLogApi.connectMergeStream(runnerId)
			: devRunnerLogApi.connectStream(runnerId, this.options.getSinceLine());
		this.eventSource.onopen = () => {
			this.connected = 'connected';
			this.sseStarted = true;
			this.reconnectBackoff.reset();
			this.consecutiveErrors = 0;
		};
		this.eventSource.onmessage = (event) => {
			if (event.data === '__MERGE_COMPLETED__') return;
			this.options.addLine(event.data, false);
		};
		this.eventSource.addEventListener('redis_disconnected', (event) => {
			this.redisAvailable = false;
			const data = (event as MessageEvent).data;
			this.options.addLine(`[SSE] redis_disconnected: ${data || 'Redis not available'}`, false);
		});
		this.eventSource.addEventListener('fallback_mode', (event) => {
			const data = (event as MessageEvent).data;
			this.options.addLine(`[SSE] fallback_mode: ${data || 'file polling active'}`, false);
		});
		this.eventSource.addEventListener('stream_error', (event) => {
			this.connected = 'disconnected';
			const data = (event as MessageEvent).data;
			this.options.addLine(`[SSE] stream_error: ${data || 'stream stopped'}`, false);
		});
		this.eventSource.addEventListener('connected', () => {
			this.redisAvailable = true;
			if (this.options.running()) {
				this.options.clearExitBanner();
			}
		});
		this.eventSource.addEventListener('completed', (event: MessageEvent) => {
			this.complete((event as MessageEvent).data || 'completed');
		});
		this.eventSource.onerror = async () => {
			if (this.options.hasExitBanner()) return;
			this.consecutiveErrors += 1;
			this.close();

			this.connected = 'disconnected';

			if (!this.redisAvailable && this.reconnectBackoff.attempts >= 5) {
				return;
			}

			await this.fetchStatus();
			const delay = this.reconnectBackoff.nextDelay() ?? 60000;
			this.clearReconnectTimer();
			this.reconnectTimer = setTimeout(() => {
				void this.connect();
			}, delay);
		};
	}

	private close(): void {
		this.eventSource?.close();
		this.eventSource = null;
	}

	private clearReconnectTimer(): void {
		if (!this.reconnectTimer) return;
		clearTimeout(this.reconnectTimer);
		this.reconnectTimer = null;
	}
}
