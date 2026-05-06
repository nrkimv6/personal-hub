/**
 * Quota 상태 전역 store 및 체크 유틸리티
 *
 * - quota-status API 응답을 캐싱 (5분 TTL)
 * - getQuotaWarning(provider) 로 토스트 메시지 문자열 반환
 */
import { writable, get } from 'svelte/store';
import { isApiGateClosedError } from '$lib/api/client';

export interface QuotaProviderStatus {
	paused: boolean;
	until?: string;
	reason?: string | null;
	remaining_seconds?: number;
	pending_blocked_count?: number;
	timezone?: string;
}

export type QuotaStatusMap = Record<string, QuotaProviderStatus>;

export interface ProfileQuotaStatus {
	engine: string;
	profile_name: string;
	state: 'available' | 'paused_by_quota' | 'paused_by_window' | 'disabled' | 'processing';
	quota_reset_at?: string | null;
	next_allowed_at?: string | null;
	blocked_request_count?: number;
	processing_count?: number;
	last_error_summary?: string | null;
	priority?: number;
}

// 전역 store
export const quotaStatus = writable<QuotaStatusMap>({});
export const profileQuotaStatus = writable<ProfileQuotaStatus[]>([]);

// 마지막 fetch 시각 (TTL 계산용)
let lastFetchedAt: number | null = null;
let lastProfileFetchedAt: number | null = null;
const TTL_MS = 5 * 60 * 1000; // 5분

/**
 * GET /api/v1/llm/quota-status 호출 후 store 갱신
 * 5분 TTL 캐시 — force=true 시 TTL 무시
 */
export async function fetchQuotaStatus(force = false): Promise<void> {
	const now = Date.now();
	if (!force && lastFetchedAt !== null && now - lastFetchedAt < TTL_MS) {
		return; // 캐시 유효
	}

	try {
		const res = await fetch('/api/v1/llm/quota-status');
		if (!res.ok) return;
		const data: QuotaStatusMap = await res.json();
		quotaStatus.set(data);
		lastFetchedAt = now;
	} catch (e) {
		if (isApiGateClosedError(e)) return;
		// 네트워크 오류 시 기존 store 유지
	}
}

export async function fetchProfileQuotaStatus(force = false): Promise<void> {
	const now = Date.now();
	if (!force && lastProfileFetchedAt !== null && now - lastProfileFetchedAt < TTL_MS) {
		return;
	}

	try {
		const res = await fetch('/api/v1/llm/profiles/status');
		if (!res.ok) return;
		const data: ProfileQuotaStatus[] = await res.json();
		profileQuotaStatus.set(data);
		lastProfileFetchedAt = now;
	} catch (e) {
		if (isApiGateClosedError(e)) return;
	}
}

/**
 * Xh Ym / M분 S초 포맷
 * (llm-pending-wait-info plan과 공유 가능)
 */
export function formatWaitTime(seconds: number): string {
	if (seconds <= 0) return '곧 재개';
	const h = Math.floor(seconds / 3600);
	const m = Math.floor((seconds % 3600) / 60);
	const s = seconds % 60;

	if (h > 0) {
		return m > 0 ? `${h}h ${m}m` : `${h}h`;
	}
	if (m > 0) {
		return s > 0 ? `${m}분 ${s}초` : `${m}분`;
	}
	return `${s}초`;
}

/**
 * provider의 quota pause 중이면 경고 문자열 반환, 아니면 null
 *
 * @example
 * const warn = getQuotaWarning('gemini');
 * if (warn) toast.warning(warn);
 */
export function getQuotaWarning(provider: string): string | null {
	const status = get(quotaStatus);
	const entry = status[provider];

	if (!entry || !entry.paused) return null;

	const providerLabel = provider.charAt(0).toUpperCase() + provider.slice(1);
	const reason = entry.reason ? ` (${entry.reason})` : '';

	if (entry.remaining_seconds != null && entry.remaining_seconds > 0) {
		const waitStr = formatWaitTime(entry.remaining_seconds);
		return `${providerLabel} 쿼터 소진${reason} — ${waitStr} 후 재개 예정`;
	}

	if (entry.until) {
		return `${providerLabel} 쿼터 소진${reason} — ${entry.until} 이후 재개 예정`;
	}

	return `${providerLabel} 쿼터 소진${reason} — 일시 정지 중`;
}

export function summarizeProfileCapacity(
	provider: string,
	profiles: ProfileQuotaStatus[]
): string | null {
	const providerProfiles = profiles.filter((p) => p.engine === provider);
	if (providerProfiles.length === 0) return null;
	if (providerProfiles.some((p) => p.state === 'available')) return null;

	const quota = providerProfiles.filter((p) => p.state === 'paused_by_quota').length;
	const window = providerProfiles.filter((p) => p.state === 'paused_by_window').length;
	const disabled = providerProfiles.filter((p) => p.state === 'disabled').length;
	const processing = providerProfiles.filter((p) => p.state === 'processing').length;

	return `현재 가능한 profile 없음(quota: ${quota}, window: ${window}, disabled: ${disabled}, processing: ${processing})`;
}
