import { json, type RequestEvent } from '@sveltejs/kit';
import { getGateSnapshot, openGate } from '$lib/server/api-gate-state';
import { assertLocalRequest } from '$lib/server/recovery-guard';

export async function POST(event: RequestEvent) {
	assertLocalRequest(event);

	let body: unknown = {};
	try {
		body = await event.request.json();
	} catch {
		body = {};
	}

	const payload = body && typeof body === 'object' ? body as Record<string, unknown> : {};
	const reason = typeof payload.reason === 'string' && payload.reason.trim()
		? payload.reason.trim()
		: 'manual';

	openGate(reason);
	return json({ success: true, gate: getGateSnapshot() });
}
