/**
 * 쿠팡 여행상품 모니터링 API 클라이언트
 */

import { request } from './client';

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
  product_id: string | null;
  item_name: string | null;
  business_name: string | null;
  service_account_id: number | null;
}

export interface CreateTargetRequest {
  url: string;
  vendor_item_package_id: string;
  name: string;
}

export interface CreateScheduleRequest {
  biz_item_id: number;
  dates: string[];
  service_account_id: number;
}

// ========== API ==========

export const coupangTravelApi = {
  async listTargets(): Promise<CoupangTarget[]> {
    return request<CoupangTarget[]>(`${BASE}/targets`);
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

  async listSchedules(): Promise<CoupangSchedule[]> {
    return request<CoupangSchedule[]>(`${BASE}/schedules`);
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
  }
};
