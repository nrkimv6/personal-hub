import {
	formatLLMBlockReason,
	type LLMProfileConfig,
	type LLMRequest,
	type LLMScheduleProfilePolicyItem,
	type LLMScheduleProfilePolicyWindow,
	type ProviderInfo,
	type QuotaStatusMap
} from '$lib/api';
import type { LlmPendingPauseInfo } from './types';

export function errorMessage(e: unknown): string {
	return e instanceof Error ? e.message : '알 수 없는 오류';
}

export function parsePolicyWindows(value: string): LLMScheduleProfilePolicyWindow[] {
	const trimmed = value.trim();
	if (!trimmed) return [];
	if (trimmed.startsWith('[')) {
		return JSON.parse(trimmed) as LLMScheduleProfilePolicyWindow[];
	}
	return trimmed.split(/\r?\n/)
		.map(line => line.trim())
		.filter(Boolean)
		.map(line => {
			const [timeRange, daysPart] = line.split(/\s+/);
			const [start, end] = timeRange.split('-');
			if (!start || !end) {
				throw new Error('window 형식은 HH:MM-HH:MM 입니다');
			}
			const policyWindow: LLMScheduleProfilePolicyWindow = { start, end };
			if (daysPart) {
				policyWindow.days = daysPart.split(',').map(day => Number(day.trim()));
			}
			return policyWindow;
		});
}

export function formatPolicyWindows(windows: LLMScheduleProfilePolicyWindow[]): string {
	if (!windows.length) return '-';
	return windows.map(policyWindow => {
		const days = policyWindow.days?.length ? ` ${policyWindow.days.join(',')}` : '';
		return `${policyWindow.start}-${policyWindow.end}${days}`;
	}).join(', ');
}

export function formatPolicyScope(policy: LLMScheduleProfilePolicyItem): string {
	if (policy.schedule_id) return `schedule #${policy.schedule_id}`;
	return policy.target_type || 'global';
}

export function getPolicyBlockReasonLabel(reason: string): string {
	return formatLLMBlockReason(reason);
}

export function profileOptionsForEngine(
	profiles: LLMProfileConfig[],
	engine: string
): LLMProfileConfig[] {
	return profiles.filter(profile => profile.engine === engine);
}

export function policyEngines(profiles: LLMProfileConfig[], fallbackEngine: string): string[] {
	const engines = Array.from(new Set(profiles.map(profile => profile.engine)));
	return engines.length > 0 ? engines : [fallbackEngine];
}

export function getProviderModels(providers: ProviderInfo[], providerKey: string): string[] {
	const provider = providers.find(item => item.key === providerKey);
	if (provider && provider.models.length > 0) return ['(기본)', ...provider.models];
	return ['(기본)'];
}

export function getGroupKey(group: { caller_type: string; caller_id: string }): string {
	return `${group.caller_type}:${group.caller_id}`;
}

export function truncatePrompt(prompt: string, maxLength: number = 80): string {
	if (!prompt) return '-';
	if (prompt.length <= maxLength) return prompt;
	return prompt.substring(0, maxLength) + '...';
}

export function formatWaitTime(seconds: number): string {
	if (seconds <= 0) return '곧 재개';
	const h = Math.floor(seconds / 3600);
	const m = Math.floor((seconds % 3600) / 60);
	const s = seconds % 60;
	if (h > 0) return `${h}시간 ${m}분`;
	if (m > 0) return `${m}분 ${s}초`;
	return `${s}초`;
}

export function formatDateTime(isoString: string | null | undefined): string {
	if (!isoString) return '-';
	try {
		const date = new Date(isoString);
		return date.toLocaleString('ko-KR', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	} catch {
		return '-';
	}
}

export function getStatusColor(status: string): string {
	switch (status) {
		case 'pending': return 'bg-warning-light text-warning-foreground';
		case 'processing': return 'bg-primary-light text-primary';
		case 'completed': return 'bg-success-light text-success';
		case 'failed': return 'bg-error-light text-error';
		case 'cancelled': return 'bg-muted text-foreground';
		default: return 'bg-muted text-foreground';
	}
}

export function getStatusLabel(status: string): string {
	switch (status) {
		case 'pending': return '대기';
		case 'processing': return '처리중';
		case 'completed': return '완료';
		case 'failed': return '실패';
		case 'cancelled': return '취소';
		default: return status;
	}
}

export function getPendingPauseInfo(
	request: LLMRequest,
	quotaStatus: QuotaStatusMap
): LlmPendingPauseInfo | null {
	if (request.status !== 'pending') return null;
	if (request.pending_block_reason) {
		return {
			label: formatLLMBlockReason(request.pending_block_reason),
			title: request.pending_block_reason,
			tone: 'quota'
		};
	}
	const windowPause = quotaStatus.__execution_window;
	if (windowPause?.paused) {
		const wait = windowPause.remaining_seconds != null ? formatWaitTime(windowPause.remaining_seconds) : null;
		return {
			label: '시간창 보류',
			title: wait ? `다음 실행 가능 시간까지 ${wait}` : '현재 실행 가능 시간창 밖입니다',
			tone: 'window'
		};
	}
	const provider = request.provider || 'claude';
	const providerPause = quotaStatus[provider];
	if (providerPause?.paused) {
		const wait = providerPause.remaining_seconds != null ? formatWaitTime(providerPause.remaining_seconds) : null;
		return {
			label: '쿼터 보류',
			title: wait ? `${provider} 쿼터 재개까지 ${wait}` : providerPause.reason || `${provider} 쿼터 일시정지`,
			tone: 'quota'
		};
	}
	return null;
}
