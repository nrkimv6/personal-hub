import { getExitReasonDisplay } from './dev-runner-exit-reason';

/**
 * merge_log_completed SSE에서 "❌ 머지 실패" 배너를 표시해야 하는지 판정.
 * LogViewer.svelte의 injectMergeCompleted에서 사용하며, 순수 함수 분리로 node --test 검증 가능.
 */
export function shouldShowMergeCompletionBanner(reason?: string | null, status?: string | null): boolean {
	if (status === 'failed') return true;
	if (!reason) return false;
	const normalized = getExitReasonDisplay(reason).reason;
	return !['completed', 'stopped', 'archived', 'on_hold', 'unknown'].includes(normalized);
}
