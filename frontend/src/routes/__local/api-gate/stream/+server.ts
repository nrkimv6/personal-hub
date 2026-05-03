import type { RequestEvent } from '@sveltejs/kit';
import { subscribe } from '$lib/server/api-gate-state';

const encoder = new TextEncoder();

function encodeSse(event: string, data: unknown): Uint8Array {
	return encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

export function GET(event: RequestEvent) {
	let unsubscribe: (() => void) | null = null;
	let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

	const stream = new ReadableStream<Uint8Array>({
		start(controller) {
			unsubscribe = subscribe((snapshot) => {
				controller.enqueue(encodeSse('gate_state', snapshot));
			});

			heartbeatTimer = setInterval(() => {
				controller.enqueue(encodeSse('heartbeat', {}));
			}, 10000);

			event.request.signal.addEventListener('abort', () => {
				unsubscribe?.();
				unsubscribe = null;
				if (heartbeatTimer !== null) {
					clearInterval(heartbeatTimer);
					heartbeatTimer = null;
				}
				controller.close();
			}, { once: true });
		},
		cancel() {
			unsubscribe?.();
			unsubscribe = null;
			if (heartbeatTimer !== null) {
				clearInterval(heartbeatTimer);
				heartbeatTimer = null;
			}
		}
	});

	return new Response(stream, {
		headers: {
			'Content-Type': 'text/event-stream',
			'Cache-Control': 'no-cache, no-transform',
			Connection: 'keep-alive'
		}
	});
}
