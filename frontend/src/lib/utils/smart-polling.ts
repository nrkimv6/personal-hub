/**
 * Smart Polling Utility
 * 실행 상태와 탭 가시성에 따라 동적으로 폴링 간격을 조정합니다.
 */

export interface SmartPollingOptions {
	/** 실행 중 + 탭 활성: 빠른 피드백 (기본: 3000ms) */
	fastInterval?: number;
	/** 중지 + 탭 활성: 변경 가능성 낮음 (기본: 15000ms) */
	slowInterval?: number;
	/** 탭 비활성: 리소스 절약 (기본: 30000ms) */
	idleInterval?: number;
	/** 에러 핸들러 (콜백 실패 시 호출) */
	onError?: (error: Error) => void;
}

export interface SmartPollingState {
	/** 현재 실행 중인지 여부 */
	running: boolean;
}

/**
 * 현재 상태에 따라 적절한 폴링 간격을 반환합니다.
 */
export function getPollingInterval(
	isRunning: boolean,
	isTabVisible: boolean,
	options: SmartPollingOptions = {}
): number {
	const { fastInterval = 3000, slowInterval = 15000, idleInterval = 30000 } = options;

	// 탭이 비활성화된 경우 가장 긴 간격 사용
	if (!isTabVisible) {
		return idleInterval;
	}

	// 실행 중이면 빠른 간격, 아니면 느린 간격
	return isRunning ? fastInterval : slowInterval;
}

export interface SmartPollingController {
	/** cleanup 함수 */
	cleanup: () => void;
	/** 상태 변경 시 폴링 간격 재평가 */
	refresh: () => void;
}

/**
 * 스마트 폴링 팩토리 함수
 * 상태에 따라 자동으로 폴링 간격을 조정합니다.
 */
export function createSmartPolling(
	callback: () => void | Promise<void>,
	getState: () => SmartPollingState,
	options: SmartPollingOptions = {}
): SmartPollingController {
	let intervalId: ReturnType<typeof setInterval> | null = null;
	let isTabVisible = !document.hidden;
	let currentInterval = 0;

	function updatePolling() {
		const state = getState();
		const newInterval = getPollingInterval(state.running, isTabVisible, options);

		// 간격이 변경되었을 때만 재설정
		if (newInterval !== currentInterval) {
			if (intervalId !== null) {
				clearInterval(intervalId);
			}
			currentInterval = newInterval;

			// 에러 핸들링이 포함된 콜백 래퍼
			const wrappedCallback = async () => {
				try {
					await callback();
				} catch (error) {
					console.error('[smart-polling] Callback error:', error);
					options?.onError?.(error instanceof Error ? error : new Error(String(error)));
				}
			};

			intervalId = setInterval(wrappedCallback, currentInterval);
		}
	}

	function handleVisibilityChange() {
		isTabVisible = !document.hidden;
		updatePolling();
	}

	// 초기 폴링 시작
	updatePolling();

	// 탭 가시성 변경 감지
	document.addEventListener('visibilitychange', handleVisibilityChange);

	// cleanup 함수 및 refresh 함수 반환
	return {
		cleanup: () => {
			if (intervalId !== null) {
				clearInterval(intervalId);
				intervalId = null;
			}
			document.removeEventListener('visibilitychange', handleVisibilityChange);
		},
		refresh: updatePolling
	};
}
