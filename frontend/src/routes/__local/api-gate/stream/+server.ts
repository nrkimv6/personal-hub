import type { RequestEvent } from '@sveltejs/kit';
import { subscribe } from '$lib/server/api-gate-state';

const encoder = new TextEncoder();

function encodeSse(event: string, data: unknown): Uint8Array {
	return encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

export function GET(event: RequestEvent) {
	let unsubscribe: (() => void) | null = null;
	let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
	let streamClosed = false;

	function cleanup() {
		unsubscribe?.();
		unsubscribe = null;
		if (heartbeatTimer !== null) {
			clearInterval(heartbeatTimer);
			heartbeatTimer = null;
		}
	}

	const stream = new ReadableStream<Uint8Array>({
		start(controller) {
			function safeClose() {
				if (streamClosed) return;
				streamClosed = true;
				cleanup();
				try {
					controller.close();
				} catch {
					// The platform may have already closed or errored this stream.
				}
			}

			function safeEnqueue(eventName: string, data: unknown) {
				if (streamClosed) return;
				try {
					controller.enqueue(encodeSse(eventName, data));
				} catch {
					streamClosed = true;
					cleanup();
				}
			}

			unsubscribe = subscribe((snapshot) => {
				safeEnqueue('gate_state', snapshot);
			});

			heartbeatTimer = setInterval(() => {
				safeEnqueue('heartbeat', {});
			}, 10000);

			event.request.signal.addEventListener('abort', () => {
				safeClose();
			}, { once: true });
		},
		cancel() {
			streamClosed = true;
			cleanup();
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
