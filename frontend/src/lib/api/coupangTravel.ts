/**
 * 쿠팡 여행상품 모니터링 API 클라이언트
 */

import { request } from './client';
import type { MonitoringEventListParams } from './naver-booking';
import type { MonitoringEventList } from '$lib/types';

const BASE = '/coupang';

// ========== Types ==========

export interface CoupangTarget {
  id: number;
  product_id: string;
  name: string;
  business_pk: number;
  is_enabled: boolean;
}

export interface CoupangSchedule {
  id: number;
  date: string;
  is_enabled: boolean;
  is_active: boolean;
  product_id: string | null;
  item_name: string | null;
  business_name: string | null;
  service_account_id: number | null;
}

export interface CoupangStatusSummary {
  total_schedules: number;
  enabled_schedules: number;
  active_schedules: number;
}

export interface CreateTargetRequest {
  url: string;
  vendor_item_package_id: string;
  name: string;
}

export interface CreateScheduleRequest {
  biz_item_id: number;
  dates: string[];
  service_account_id?: number;
}

// ── 취소표 통계 타입 ──────────────────────────────────────────────────────────

export interface CancellationStatsParams {
  date_from?: string;
  date_to?: string;
  biz_item_id?: number;
  hours?: string;        // 쉼표 구분 (예: "13,15,18")
  group_by?: 'day' | 'hour';
}

export interface CancellationStatItem {
  date?: string | null;
  hour?: number | null;
  count: number;
  biz_item_id?: number | null;
  biz_item_name?: string | null;
}

export interface CancellationStatsSummary {
  total: number;
  avg_per_day: number;
  peak_hour?: number | null;
}

export interface CancellationStatsResponse {
  items: CancellationStatItem[];
  summary: CancellationStatsSummary;
}

export interface CancellationByProductItem {
  biz_item_id: number;
  biz_item_name: string;
  business_name: string;
  total_count: number;
  last_detected?: string | null;
  avg_interval_hours?: number | null;
}

export interface CancellationByProductResponse {
  items: CancellationByProductItem[];
}

// ========== API ==========

export const coupangTravelApi = {
  async listTargets(options?: RequestInit): Promise<CoupangTarget[]> {
    return request<CoupangTarget[]>(`${BASE}/targets`, options);
  },

  async createTarget(body: CreateTargetRequest): Promise<{ id: number; product_id: string }> {
    return request(`${BASE}/targets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  },

  async deleteTarget(id: number): Promise<void> {
    await request(`${BASE}/targets/${id}`, { method: 'DELETE' });
  },

  async listSchedules(options?: RequestInit): Promise<CoupangSchedule[]> {
    return request<CoupangSchedule[]>(`${BASE}/schedules`, options);
  },

  async createSchedules(body: CreateScheduleRequest): Promise<{ created: number }> {
    return request(`${BASE}/schedules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  },

  async deleteSchedule(id: number): Promise<void> {
    await request(`${BASE}/schedules/${id}`, { method: 'DELETE' });
  },

  async enableSchedule(id: number): Promise<{ id: number; is_enabled: boolean }> {
    return request(`${BASE}/schedules/${id}/enable`, { method: 'POST' });
  },

  async disableSchedule(id: number): Promise<{ id: number; is_enabled: boolean }> {
    return request(`${BASE}/schedules/${id}/disable`, { method: 'POST' });
  },

  async getStatus(options?: RequestInit): Promise<CoupangStatusSummary> {
    return request<CoupangStatusSummary>(`${BASE}/status`, options);
  },

  async cleanupSchedules(): Promise<{ deleted: number }> {
    return request<{ deleted: number }>(`${BASE}/schedules/cleanup`, { method: 'POST' });
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
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));
    searchParams.append('service_type', 'coupang');
    const query = searchParams.toString();
    return request<MonitoringEventList>(`/monitoring/events${query ? `?${query}` : ''}`, options);
  },

  async getCancellationStats(
    params?: CancellationStatsParams,
    options?: RequestInit
  ): Promise<CancellationStatsResponse> {
    const searchParams = new URLSearchParams();
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    if (params?.biz_item_id != null) searchParams.append('biz_item_id', String(params.biz_item_id));
    if (params?.hours) searchParams.append('hours', params.hours);
    if (params?.group_by) searchParams.append('group_by', params.group_by);
    const query = searchParams.toString();
    return request<CancellationStatsResponse>(
      `/monitoring/events/cancellation-stats${query ? `?${query}` : ''}`,
      options
    );
  },

  async getCancellationByProduct(
    params?: Omit<CancellationStatsParams, 'group_by'>,
    options?: RequestInit
  ): Promise<CancellationByProductResponse> {
    const searchParams = new URLSearchParams();
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    if (params?.hours) searchParams.append('hours', params.hours);
    const query = searchParams.toString();
    return request<CancellationByProductResponse>(
      `/monitoring/events/cancellation-by-product${query ? `?${query}` : ''}`,
      options
    );
  }
};
