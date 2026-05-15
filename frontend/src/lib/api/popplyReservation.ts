import { request } from './client';
import type { MonitoringEventListParams } from './naver-booking';
import type { MonitoringEventList } from '$lib/types';

const BASE = '/popply';

export interface PopplyTarget {
	id: number;
	store_id: string;
	name: string;
	source_url: string;
	schedule_group: string;
	reservation_type: string;
	is_enabled: boolean;
}

export interface PopplySchedule {
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
	store_id: string | null;
	schedule_group: string | null;
}

export interface CreatePopplyTargetRequest {
	source_url: string;
	name?: string;
}

export interface CreatePopplyScheduleRequest {
	biz_item_id: number;
	dates: string[];
}

export const popplyReservationApi = {
	async listTargets(options?: RequestInit): Promise<PopplyTarget[]> {
		return request<PopplyTarget[]>(`${BASE}/targets`, options);
	},

	async createTarget(body: CreatePopplyTargetRequest): Promise<PopplyTarget> {
		return request<PopplyTarget>(`${BASE}/targets`, {
			method: 'POST',
			body: JSON.stringify(body)
		});
	},

	async deleteTarget(id: number): Promise<void> {
		await request(`${BASE}/targets/${id}`, { method: 'DELETE' });
	},

	async listSchedules(options?: RequestInit): Promise<PopplySchedule[]> {
		return request<PopplySchedule[]>(`${BASE}/schedules`, options);
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
		searchParams.append('service_type', 'popply');
		const query = searchParams.toString();
		return request<MonitoringEventList>(`/monitoring/events${query ? `?${query}` : ''}`, options);
	},

	async createSchedules(body: CreatePopplyScheduleRequest): Promise<{ created: number }> {
		return request<{ created: number }>(`${BASE}/schedules`, {
			method: 'POST',
			body: JSON.stringify(body)
		});
	},

	async enableSchedule(id: number): Promise<PopplySchedule> {
		return request<PopplySchedule>(`${BASE}/schedules/${id}/enable`, { method: 'POST' });
	},

	async disableSchedule(id: number): Promise<PopplySchedule> {
		return request<PopplySchedule>(`${BASE}/schedules/${id}/disable`, { method: 'POST' });
	},

	async deleteSchedule(id: number): Promise<void> {
		await request(`${BASE}/schedules/${id}`, { method: 'DELETE' });
	},

	async checkNow(id: number): Promise<{ schedule_id: number; status: string; available_count: number }> {
		return request(`${BASE}/schedules/${id}/check-now`, { method: 'POST' });
	}
};
