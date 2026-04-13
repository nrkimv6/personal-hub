/**
 * 통합 모니터링 API 어댑터
 * - 각 모듈의 API를 호출하여 UnifiedMonitorItem으로 정규화
 * - Promise.allSettled로 부분 실패 허용
 */

import { scheduleApi } from './naver-booking';
import { coupangTravelApi } from './coupangTravel';
import { getConfigs, toggleConfig } from './kakaoMonitor';
import { activityApi, formatActivityRegion } from './activity';
import { eventApi } from './system';
import type { UnifiedMonitorItem, MonitorStatus, MonitorType } from '$lib/types/monitoring';

// ─── 내부 헬퍼 ───────────────────────────────────────────────

function naverRunStatusToMonitorStatus(runStatus: string, isEnabled: boolean): MonitorStatus {
	if (!isEnabled) return 'disabled';
	if (runStatus === 'running') return 'running';
	if (runStatus === 'error') return 'error';
	return 'idle';
}

function coupangStatusToMonitorStatus(isEnabled: boolean, isActive: boolean): MonitorStatus {
	if (!isEnabled) return 'disabled';
	if (isActive) return 'running';
	return 'idle';
}

function kakaoStatusToMonitorStatus(isActive: boolean): MonitorStatus {
	return isActive ? 'running' : 'disabled';
}

// ─── 모듈별 fetch 함수 ────────────────────────────────────────

export async function fetchNaverItems(): Promise<UnifiedMonitorItem[]> {
	const items = await scheduleApi.listWithContext();
	return items.map((s) => ({
		id: `naver-${s.id}`,
		type: 'naver' as MonitorType,
		name: s.item_name ?? `일정 #${s.id}`,
		status: naverRunStatusToMonitorStatus(s.run_status, s.is_enabled),
		lastChecked: s.updated_at,
		summary: s.times?.join(', ') ?? undefined,
		detailHref: '/naver',
		toggleable: true
	}));
}

export async function fetchCoupangItems(): Promise<UnifiedMonitorItem[]> {
	const items = await coupangTravelApi.listSchedules();
	return items.map((s) => ({
		id: `coupang-${s.id}`,
		type: 'coupang' as MonitorType,
		name: s.item_name ?? `쿠팡 일정 ${s.date}`,
		status: coupangStatusToMonitorStatus(s.is_enabled, s.is_active),
		summary: s.business_name ?? undefined,
		detailHref: '/coupang',
		toggleable: true
	}));
}

export async function fetchKakaoItems(): Promise<UnifiedMonitorItem[]> {
	const configs = await getConfigs();
	return configs.map((c) => ({
		id: `kakao-${c.id}`,
		type: 'kakao' as MonitorType,
		name: c.chat_name,
		status: kakaoStatusToMonitorStatus(c.is_active),
		summary: `키워드 ${c.keyword_count}개`,
		detailHref: '/kakao-monitor',
		toggleable: true
	}));
}

export async function fetchActivityItems(): Promise<UnifiedMonitorItem[]> {
	const centers = (await activityApi.listCenters({ page_size: 100 })).items;
	return centers.map((c) => ({
		id: `activity-${c.id}`,
		type: 'activity' as MonitorType,
		name: c.name,
		status: 'idle' as MonitorStatus,
		summary: formatActivityRegion(c),
		detailHref: '/activity',
		toggleable: false
	}));
}

export async function fetchEventItems(): Promise<UnifiedMonitorItem[]> {
	const result = await eventApi.list({ page_size: 1 });
	return [
		{
			id: 'event-summary',
			type: 'event' as MonitorType,
			name: '이벤트 모음',
			status: 'idle' as MonitorStatus,
			summary: `총 ${result.total}건`,
			detailHref: '/events',
			toggleable: false
		}
	];
}

// ─── 병렬 통합 fetch ─────────────────────────────────────────

export interface FetchAllResult {
	items: UnifiedMonitorItem[];
	errors: { module: string; message: string }[];
}

export async function fetchAllMonitorItems(types?: MonitorType[]): Promise<FetchAllResult> {
	const fetchers: { key: string; type: MonitorType; fn: () => Promise<UnifiedMonitorItem[]> }[] = [
		{ key: '네이버', type: 'naver', fn: fetchNaverItems },
		{ key: '쿠팡', type: 'coupang', fn: fetchCoupangItems },
		{ key: '카카오', type: 'kakao', fn: fetchKakaoItems },
		{ key: '체육센터', type: 'activity', fn: fetchActivityItems },
		{ key: '이벤트', type: 'event', fn: fetchEventItems }
	];

	const active = types ? fetchers.filter((f) => types.includes(f.type)) : fetchers;
	const results = await Promise.allSettled(active.map((f) => f.fn()));

	const items: UnifiedMonitorItem[] = [];
	const errors: { module: string; message: string }[] = [];

	results.forEach((result, i) => {
		if (result.status === 'fulfilled') {
			items.push(...result.value);
		} else {
			errors.push({
				module: active[i].key,
				message: result.reason instanceof Error ? result.reason.message : String(result.reason)
			});
		}
	});

	return { items, errors };
}

// ─── 상태 토글 어댑터 ─────────────────────────────────────────

export async function toggleMonitorItem(item: UnifiedMonitorItem): Promise<void> {
	const enabled = item.status !== 'disabled';
	const rawId = parseInt(item.id.split('-').slice(1).join('-'), 10);

	if (item.type === 'naver') {
		if (enabled) {
			await scheduleApi.disable(rawId);
		} else {
			await scheduleApi.enable(rawId);
		}
	} else if (item.type === 'coupang') {
		if (enabled) {
			await coupangTravelApi.disableSchedule(rawId);
		} else {
			await coupangTravelApi.enableSchedule(rawId);
		}
	} else if (item.type === 'kakao') {
		await toggleConfig(rawId);
	}
}
