export type GateStateName = 'open' | 'closed' | 'recovering';
export type GateEventType = 'close' | 'open' | 'recovering';

export interface GateEvent {
	type: GateEventType;
	reason: string;
	apiPort: number | null;
	timestamp: number;
}

export interface GateSnapshot {
	state: GateStateName;
	reason: string;
	since: number | null;
	apiPort: number | null;
	recentEvents: GateEvent[];
}

type Subscriber = (snapshot: GateSnapshot) => void;

const RECOVERY_INTERVAL_MS = 2000;
const REQUIRED_READY_SUCCESSES = 3;
const MAX_RECENT_EVENTS = 20;

let state: GateStateName = 'open';
let reason = '';
let since: number | null = null;
let apiPort: number | null = null;
let recentEvents: GateEvent[] = [];
let recoveryTimer: ReturnType<typeof setInterval> | null = null;
let readySuccessCount = 0;

const subscribers = new Set<Subscriber>();

function buildReadyUrl(port: number): string {
	if (port !== 8000 && port !== 8001) {
		throw new Error(`Unsupported API port: ${port}`);
	}
	return `http://127.0.0.1:${port}/api/v1/ready`;
}

function snapshot(): GateSnapshot {
	return {
		state,
		reason,
		since,
		apiPort,
		recentEvents: [...recentEvents]
	};
}

function pushEvent(type: GateEventType, nextReason: string, nextApiPort: number | null): void {
	recentEvents = [
		...recentEvents,
		{
			type,
			reason: nextReason,
			apiPort: nextApiPort,
			timestamp: Date.now()
		}
	].slice(-MAX_RECENT_EVENTS);
	console.log(`[api-gate] ${type}: port=${nextApiPort ?? 'none'} reason=${nextReason}`);
}

function broadcast(): void {
	const nextSnapshot = snapshot();
	for (const cb of subscribers) {
		cb(nextSnapshot);
	}
}

function stopRecoveryProbe(): void {
	if (recoveryTimer !== null) {
		clearInterval(recoveryTimer);
		recoveryTimer = null;
	}
	readySuccessCount = 0;
}

async function probeReady(): Promise<void> {
	if (apiPort === null) return;

	try {
		const response = await fetch(buildReadyUrl(apiPort));
		const payload = response.ok ? await response.json().catch(() => null) : null;
		if (payload?.ready === true) {
			readySuccessCount += 1;
			if (readySuccessCount >= REQUIRED_READY_SUCCESSES) {
				openGate('auto-recovery');
			}
			return;
		}
	} catch {
		// Keep the gate recovering until ready succeeds consecutively.
	}

	readySuccessCount = 0;
}

function startRecoveryProbe(): void {
	if (recoveryTimer !== null || apiPort === null) return;
	state = 'recovering';
	pushEvent('recovering', reason, apiPort);
	broadcast();
	recoveryTimer = setInterval(() => {
		void probeReady();
	}, RECOVERY_INTERVAL_MS);
	void probeReady();
}

export function closeGate(nextApiPort: number, nextReason: string): void {
	if (nextApiPort !== 8000 && nextApiPort !== 8001) {
		throw new Error(`Unsupported API port: ${nextApiPort}`);
	}
	stopRecoveryProbe();
	state = 'closed';
	reason = nextReason;
	since = Date.now();
	apiPort = nextApiPort;
	pushEvent('close', reason, apiPort);
	broadcast();
	startRecoveryProbe();
}

export function openGate(nextReason = 'manual'): void {
	stopRecoveryProbe();
	state = 'open';
	reason = nextReason;
	since = null;
	apiPort = null;
	pushEvent('open', reason, apiPort);
	broadcast();
}

export function subscribe(cb: Subscriber): () => void {
	subscribers.add(cb);
	cb(snapshot());
	return () => {
		subscribers.delete(cb);
	};
}

export function getGateSnapshot(): GateSnapshot {
	return snapshot();
}
