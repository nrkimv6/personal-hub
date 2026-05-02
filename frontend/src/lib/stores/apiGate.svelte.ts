type GateStateName = 'open' | 'closed' | 'recovering';

interface GateSnapshot {
	state: GateStateName;
	reason: string;
	since: number | null;
	apiPort: number | null;
}

const STATUS_URL = '/__local/api-gate/status';
const STREAM_URL = '/__local/api-gate/stream';
const POLL_INTERVAL_MS = 2000;
const RECONNECT_DELAYS_MS = [2000, 4000, 8000, 30000];

function createApiGateStore() {
	let state = $state<GateStateName>('open');
	let reason = $state('');
	let since = $state<number | null>(null);
	let apiPort = $state<number | null>(null);

	let eventSource: EventSource | null = null;
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let reconnectAttempt = 0;

	function applySnapshot(snapshot: GateSnapshot) {
		const previousState = state;
		state = snapshot.state;
		reason = snapshot.reason;
		since = snapshot.since;
		apiPort = snapshot.apiPort;
		if (previousState !== 'open' && state === 'open') {
			void reportGateRecoveryToApiHealth();
		}
	}

	function clearReconnectTimer() {
		if (reconnectTimer !== null) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
	}

	function stopPollingFallback() {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	function closeEventSource() {
		if (eventSource !== null) {
			eventSource.close();
			eventSource = null;
		}
	}

	async function refreshStatus(): Promise<void> {
		const response = await fetch(STATUS_URL);
		if (!response.ok) return;
		applySnapshot(await response.json());
	}

	function scheduleSseReconnect() {
		if (reconnectTimer !== null || typeof window === 'undefined') return;
		const delay = RECONNECT_DELAYS_MS[Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
		reconnectAttempt += 1;
		reconnectTimer = setTimeout(() => {
			reconnectTimer = null;
			connectSse();
		}, delay);
	}

	function startPollingFallback(): void {
		if (typeof window === 'undefined' || pollTimer !== null) return;
		void refreshStatus();
		pollTimer = setInterval(() => {
			void refreshStatus();
		}, POLL_INTERVAL_MS);
	}

	function connectSse() {
		if (typeof window === 'undefined' || eventSource !== null) return;

		const source = new EventSource(STREAM_URL);
		eventSource = source;

		source.addEventListener('gate_state', (event) => {
			try {
				applySnapshot(JSON.parse((event as MessageEvent).data));
				reconnectAttempt = 0;
				stopPollingFallback();
			} catch {
				// Ignore malformed status events; polling fallback will resync.
			}
		});

		source.onerror = () => {
			closeEventSource();
			startPollingFallback();
			scheduleSseReconnect();
		};
	}

	function start(): void {
		if (typeof window === 'undefined') return;
		clearReconnectTimer();
		connectSse();
	}

	function stop(): void {
		clearReconnectTimer();
		stopPollingFallback();
		closeEventSource();
	}

	$effect(() => {
		if (typeof window === 'undefined' || state === 'open' || since === null) return;

		const elapsedMs = Date.now() - since;
		const remainingMs = Math.max(0, 600000 - elapsedMs);
		const timer = setTimeout(() => {
			window.dispatchEvent(new CustomEvent('api-gate:stale'));
		}, remainingMs);

		return () => {
			clearTimeout(timer);
		};
	});

	return {
		get state() {
			return state;
		},
		get reason() {
			return reason;
		},
		get since() {
			return since;
		},
		get apiPort() {
			return apiPort;
		},
		start,
		startPollingFallback,
		stop,
		refreshStatus
	};
}

export const apiGate = createApiGateStore();

export async function reportGateRecoveryToApiHealth(): Promise<void> {
	const { apiHealth } = await import('./apiHealth.svelte');
	apiHealth.reportConnectionSuccess();
}
