import {
	ApiGateClosedError,
	GATE_BYPASS_PATHS,
	shouldBlockApiRequestForGate
} from '$lib/api/client';

let originalFetch: typeof fetch | null = null;
let fetchGateInstalled = false;

function resolveRequestUrl(input: RequestInfo | URL): URL | null {
	const raw = input instanceof Request ? input.url : input.toString();
	if (raw.startsWith('blob:') || raw.startsWith('data:')) return null;
	if (raw.startsWith('./') || raw.startsWith('../')) return null;

	try {
		return new URL(raw, window.location.origin);
	} catch {
		return null;
	}
}

function hasBypassHeader(input: RequestInfo | URL, init?: RequestInit): boolean {
	const headers = new Headers(input instanceof Request ? input.headers : undefined);
	if (init?.headers) {
		for (const [key, value] of new Headers(init.headers)) {
			headers.set(key, value);
		}
	}
	return headers.has('x-api-gate-bypass');
}

function shouldBypassGate(url: URL, input: RequestInfo | URL, init?: RequestInit): boolean {
	const path = url.pathname;
	if (path.startsWith('/__local/') || path.startsWith('/_app/')) return true;
	if (path.endsWith('/__data.json') || path === '/__data.json') return true;
	if (GATE_BYPASS_PATHS.includes(path as typeof GATE_BYPASS_PATHS[number])) return true;
	return hasBypassHeader(input, init);
}

function installFetchGate() {
	if (fetchGateInstalled || typeof window === 'undefined') return;
	originalFetch = window.fetch.bind(window);
	window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
		const url = resolveRequestUrl(input);
		if (
			url !== null &&
			!shouldBypassGate(url, input, init) &&
			shouldBlockApiRequestForGate(url.toString())
		) {
			return Promise.reject(new ApiGateClosedError());
		}

		return originalFetch!(input, init);
	}) as typeof fetch;
	fetchGateInstalled = true;
}

export function init() {
	installFetchGate();
}

export function handleError({ error }: { error: unknown }) {
	if (error instanceof ApiGateClosedError) {
		return { message: error.message };
	}
	if (error instanceof Error) {
		return { message: error.message };
	}
	return { message: 'Unexpected client error' };
}
