import { json } from '@sveltejs/kit';
import type { RequestEvent } from './$types';
import { closeGate, getGateSnapshot } from '$lib/server/api-gate-state';
import { assertLocalRequest } from '$lib/server/recovery-guard';

function parseApiPort(value: unknown): number | null {
	if (typeof value !== 'number' || !Number.isInteger(value)) return null;
	if (value !== 8000 && value !== 8001) return null;
	return value;
}

export async function POST(event: RequestEvent) {
	assertLocalRequest(event);

	let body: unknown;
	try {
		body = await event.request.json();
	} catch {
		return json({ success: false, code: 'invalid_json' }, { status: 400 });
	}

	const payload = body && typeof body === 'object' ? body as Record<string, unknown> : {};
	const apiPort = parseApiPort(payload.api_port);
	if (apiPort === null) {
		return json({ success: false, code: 'invalid_api_port' }, { status: 400 });
	}

	const reason = typeof payload.reason === 'string' && payload.reason.trim()
		? payload.reason.trim()
		: 'api restart';

	const current = getGateSnapshot();
	if (current.state === 'closed' || current.state === 'recovering') {
		return json({ success: true, status: 'already_closed', gate: current });
	}

	closeGate(apiPort, reason);
	return json({ success: true, gate: getGateSnapshot() });
}
