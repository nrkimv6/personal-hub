/**
 * fetch + ReadableStream 기반 SSE 클라이언트
 *
 * EventSource 대신 fetch를 사용하므로 서버 연결 끊김 시
 * 브라우저 콘솔에 ERR_INCOMPLETE_CHUNKED_ENCODING 에러가 출력되지 않는다.
 */

export interface FetchSSEOptions {
	url: string;
	/** named event 수신 콜백. eventName은 `event:` 필드값, 기본값은 'message' */
	onEvent?: (eventName: string, data: string) => void;
	/** 연결 성공(첫 청크 수신) 시 콜백 */
	onOpen?: () => void;
	/** 연결 오류 또는 스트림 종료 시 콜백 */
	onError?: (err: unknown) => void;
	/** fetch 요청에 추가할 headers */
	headers?: Record<string, string>;
}

export interface FetchSSEHandle {
	close: () => void;
}

/**
 * fetch 기반 SSE 연결을 생성한다.
 * 반환된 handle의 close()를 호출하면 연결을 즉시 중단한다.
 */
export function createFetchSSE(options: FetchSSEOptions): FetchSSEHandle {
	const { url, onEvent, onOpen, onError, headers } = options;
	const controller = new AbortController();

	(async () => {
		try {
			const response = await fetch(url, {
				signal: controller.signal,
				headers: {
					Accept: 'text/event-stream',
					'Cache-Control': 'no-cache',
					...headers
				},
				credentials: 'include'
			});

			if (!response.ok || !response.body) {
				onError?.(new Error(`SSE connection failed: ${response.status}`));
				return;
			}

			onOpen?.();

			const reader = response.body.getReader();
			const decoder = new TextDecoder();

			let buffer = '';
			let currentEvent = 'message';
			let currentData = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) {
					// 스트림 종료 시 마지막 버퍼/이벤트 flush
					if (buffer.length > 0) {
						const tailLine = buffer.endsWith('\r') ? buffer.slice(0, -1) : buffer;
						if (tailLine.startsWith('event:')) {
							const raw = tailLine.slice('event:'.length);
							currentEvent = raw.startsWith(' ') ? raw.slice(1) : raw;
						} else if (tailLine.startsWith('data:')) {
							const raw = tailLine.slice('data:'.length);
							const next = raw.startsWith(' ') ? raw.slice(1) : raw;
							currentData = currentData ? `${currentData}\n${next}` : next;
						}
					}
					if (currentData) {
						onEvent?.(currentEvent, currentData);
					}
					break;
				}

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				// 마지막 줄은 아직 완성되지 않을 수 있으므로 버퍼에 유지
				buffer = lines.pop() ?? '';

				for (const line of lines) {
					const normalizedLine = line.endsWith('\r') ? line.slice(0, -1) : line;
					if (normalizedLine.startsWith('event:')) {
						const raw = normalizedLine.slice('event:'.length);
						currentEvent = raw.startsWith(' ') ? raw.slice(1) : raw;
					} else if (normalizedLine.startsWith('data:')) {
						// SSE 스펙: multi data line은 '\n'로 결합하고 공백/개행 원문을 보존한다.
						const raw = normalizedLine.slice('data:'.length);
						const next = raw.startsWith(' ') ? raw.slice(1) : raw;
						currentData = currentData ? `${currentData}\n${next}` : next;
					} else if (normalizedLine === '') {
						// 빈 줄 = 이벤트 경계
						if (currentData) {
							onEvent?.(currentEvent, currentData);
						}
						// 상태 초기화
						currentEvent = 'message';
						currentData = '';
					}
				}
			}

			// 스트림 정상 종료 (서버 측 close)
			onError?.(new Error('SSE stream ended'));
		} catch (err) {
			// AbortError는 close() 호출에 의한 정상 종료 — 조용히 무시
			if (err instanceof DOMException && err.name === 'AbortError') return;
			onError?.(err);
		}
	})();

	return {
		close: () => controller.abort()
	};
}
