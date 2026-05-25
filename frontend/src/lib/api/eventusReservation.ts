/**
 * Eventus 잔여석 모니터링 API 클라이언트
 * Backend: /api/v1/eventus/...
 */
import { request } from './client';
import type { MonitoringEventListParams } from './naver-booking';
import type { MonitoringEventList } from '$lib/types';

const BASE = '/eventus';

// ─── Response types ────────────────────────────────────────────

export interface EventusSlotInfo {
	bundle_id: string;
	time_label: string | null;
	is_closed: boolean;
	closed_text: string | null;
	urgency_hint: string | null;
}

export interface EventusAnalyzeResponse {
	event_id: string | null;
	source_url: string | null;
	organizer_slug: string | null;
	channel_name: string | null;
	title: string | null;
	bundles: string[];
	slots: EventusSlotInfo[];
	closed_token_counts: number;
	error_code: string | null;
	error_message: string | null;
	fetch_method: string;
}

export interface EventusTarget {
	id: number;
	event_id: string | null;
	name: string;
	source_url: string;
	channel_name: string | null;
	organizer_slug: string | null;
	selected_bundle_id: string | null;
	selected_time_key: string | null;
	bundle_ids: string[];
	is_enabled: boolean;
}

export interface EventusSchedule {
	id: number;
	biz_item_id: number;
	date: string;
	is_enabled: boolean;
	is_active: boolean;
	run_status: string;
	last_check_time: string | null;
	last_event_at: string | null;
	last_event_status: string | null;
	item_name: string | null;
	event_id: string | null;
	selected_bundle_id: string | null;
	selected_time_key: string | null;
}

// ─── Request types ─────────────────────────────────────────────

export interface AnalyzeEventRequest {
	input: string; // event_id (digits) or full URL
}

export interface CreateEventusTargetRequest {
	source_url: string;
	name?: string;
	event_id?: string;
	organizer_slug?: string;
	channel_name?: string;
	title?: string;
	bundle_ids?: string[];
	selected_bundle_id?: string;
	selected_time_key?: string;
}

export interface CreateEventusScheduleRequest {
	biz_item_id: number;
	dates: string[];
}

// ─── API object ────────────────────────────────────────────────

export const eventusReservationApi = {
	/** Analyze event page once — returns meta + bundle/time candidates */
	async analyzeEvent(body: AnalyzeEventRequest): Promise<EventusAnalyzeResponse> {
		return request<EventusAnalyzeResponse>(`${BASE}/analyze`, {
			method: 'POST',
			body: JSON.stringify(body)
		});
	},

	async listTargets(options?: RequestInit): Promise<EventusTarget[]> {
		return request<EventusTarget[]>(`${BASE}/targets`, options);
	},

	async createTarget(body: CreateEventusTargetRequest): Promise<EventusTarget> {
		return request<EventusTarget>(`${BASE}/targets`, {
			method: 'POST',
			body: JSON.stringify(body)
		});
	},

	async deleteTarget(id: number): Promise<void> {
		await request(`${BASE}/targets/${id}`, { method: 'DELETE' });
	},

	async listSchedules(options?: RequestInit): Promise<EventusSchedule[]> {
		return request<EventusSchedule[]>(`${BASE}/schedules`, options);
	},

	async createSchedules(body: CreateEventusScheduleRequest): Promise<{ created: number }> {
		return request<{ created: number }>(`${BASE}/schedules`, {
			method: 'POST',
			body: JSON.stringify(body)
		});
	},

	async enableSchedule(id: number): Promise<EventusSchedule> {
		return request<EventusSchedule>(`${BASE}/schedules/${id}/enable`, { method: 'POST' });
	},

	async disableSchedule(id: number): Promise<EventusSchedule> {
		return request<EventusSchedule>(`${BASE}/schedules/${id}/disable`, { method: 'POST' });
	},

	async deleteSchedule(id: number): Promise<void> {
		await request(`${BASE}/schedules/${id}`, { method: 'DELETE' });
	},

	async getScheduleStatus(id: number): Promise<EventusSchedule> {
		return request<EventusSchedule>(`${BASE}/schedules/${id}/status`);
	},

	async checkNow(id: number): Promise<{ schedule_id: number; status: string; available_count: number; latest_event_id: number | null }> {
		return request(`${BASE}/schedules/${id}/check-now`, { method: 'POST' });
	},

	async listEvents(
		params?: Omit<MonitoringEventListParams, 'service_type'>,
		options?: RequestInit
	): Promise<MonitoringEventList> {
		const searchParams = new URLSearchParams();
		if (params?.schedule_id) searchParams.append('schedule_id', String(params.schedule_id));
		if (params?.biz_item_id) searchParams.append('biz_item_id', String(params.biz_item_id));
		if (params?.business_id) searchParams.append('business_id', String(params.business_id));
		if (params?.status) searchParams.append('status', params.status);
		if (params?.event_type) searchParams.append('event_type', params.event_type);
		if (params?.date_from) searchParams.append('date_from', params.date_from);
		if (params?.date_to) searchParams.append('date_to', params.date_to);
		if (params?.hours) searchParams.append('hours', params.hours);
		if (params?.page) searchParams.append('page', String(params.page));
		if (params?.page_size) searchParams.append('page_size', String(params.page_size));
		searchParams.append('service_type', 'eventus');
		const query = searchParams.toString();
		return request<MonitoringEventList>(`/monitoring/events${query ? `?${query}` : ''}`, options);
	}
};
