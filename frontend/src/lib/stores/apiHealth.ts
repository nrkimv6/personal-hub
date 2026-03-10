/**
 * 전역 API 연결 상태 Store
 *
 * API 서버 재시작 감지 및 복귀 알림을 담당합니다.
 * - disconnected 상태 감지 (연속 2회 에러 시)
 * - 백그라운드 재연결 폴링 (2초 간격)
 * - 복귀 시 'api:reconnected' 이벤트 발행
 */

const API_BASE = '/api/v1';

type ApiHealthState = 'connected' | 'disconnected' | 'reconnecting';

function createApiHealthStore() {
	let state = $state<ApiHealthState>('connected');
	let disconnectedAt = $state<number | null>(null);

	let errorCount = 0;
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	function startReconnectPolling() {
		if (pollTimer !== null) return; // 중복 시작 방지
		state = 'reconnecting';
		pollTimer = setInterval(async () => {
			try {
				const res = await fetch(`${API_BASE}/ready`);
				if (res.ok) {
					reportConnectionSuccess();
				}
			} catch {
				// 아직 연결 안 됨 — 계속 폴링
			}
		}, 2000);
	}

	function stopReconnectPolling() {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	function reportConnectionError() {
		errorCount++;
		if (errorCount >= 2 && state === 'connected') {
			state = 'disconnected';
			disconnectedAt = Date.now();
			startReconnectPolling();
		}
	}

	function reportConnectionSuccess() {
		errorCount = 0;
		if (state === 'disconnected' || state === 'reconnecting') {
			stopReconnectPolling();
			state = 'connected';
			if (typeof window !== 'undefined') {
				window.dispatchEvent(new Event('api:reconnected'));
			}
			disconnectedAt = null;
		}
	}

	return {
		get state() {
			return state;
		},
		get disconnectedAt() {
			return disconnectedAt;
		},
		reportConnectionError,
		reportConnectionSuccess
	};
}

export const apiHealth = createApiHealthStore();
