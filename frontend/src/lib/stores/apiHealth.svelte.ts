/**
 * 전역 API 연결 상태 Store
 *
 * API 서버 재시작 감지 및 복귀 알림을 담당합니다.
 * - disconnected 상태 감지 (연속 5회 에러 시)
 * - 백그라운드 재연결 폴링 (2초 간격)
 * - 복귀 시 'api:reconnected' 이벤트 발행
 */

import { apiGate } from './apiGate.svelte';

const API_BASE = '/api/v1';

type ApiHealthState = 'connected' | 'disconnected' | 'reconnecting' | 'dead';

/**
 * Tracks API reachability and death diagnostics.
 *
 * The `dead` state is only for the global unavailable overlay and diagnostics.
 * Request blocking belongs to apiGate so restart policy and health detection do
 * not compete for ownership.
 */
function createApiHealthStore() {
	let state = $state<ApiHealthState>('connected');
	let disconnectedAt = $state<number | null>(null);
	let lastDeath = $state<{ timestamp: string; cause: string; details: string } | null>(null);

	let errorCount = 0;
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	function startReconnectPolling() {
		if (pollTimer !== null) return; // 중복 시작 방지
		if (apiGate.state !== 'open') return;
		state = 'reconnecting';
		pollTimer = setInterval(async () => {
			try {
				const res = await fetch(`${API_BASE}/ready`);
				if (res.ok) {
					reportConnectionSuccess();
				}
			} catch {
				// API 연결 실패 — death_log 확인
				try {
					const statusRes = await fetch('/__local/server-status');
					if (statusRes.ok) {
						const status = await statusRes.json();
						if (status.alive === false) {
							// 폴링은 유지 — API 복귀 시 자동으로 connected로 전환되어야 함
							state = 'dead';
							lastDeath = status.lastEvent ?? null;
						}
						// alive === true: 재시작 중으로 판단, reconnecting 유지
					}
				} catch {
					// server-status 엔드포인트 오류 무시 — reconnecting 유지
				}
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
		if (errorCount >= 5 && state === 'connected') {
			state = 'disconnected';
			disconnectedAt = Date.now();
			startReconnectPolling();
		}
	}

	function reportConnectionSuccess() {
		errorCount = 0;
		if (state === 'disconnected' || state === 'reconnecting' || state === 'dead') {
			stopReconnectPolling();
			state = 'connected';
			lastDeath = null;
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
		get lastDeath() {
			return lastDeath;
		},
		reportConnectionError,
		reportConnectionSuccess
	};
}

export const apiHealth = createApiHealthStore();
