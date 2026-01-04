/**
 * Proxy API - 프록시 관리 및 사용 이력
 */
import { request } from './client';
import type {
  Proxy,
  ProxyDetail,
  ProxyStats,
  ProxyListParams,
  ProxyListResponse,
  ProxyCollectionRun,
  ProxyImportResult,
  ProxyUsageLog,
  ProxyUsageStatsResponse,
  RetryHistoryResponse,
  ProxyUsageCleanupResult
} from '../types';

// ============================================================
// Proxy API (프록시 관리)
// ============================================================

export const proxyApi = {
  // 전체 통계
  stats: () => request<ProxyStats>('/proxy/db/stats'),

  // 목록 조회 (필터, 정렬, 페이징)
  list: (params?: ProxyListParams) => {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.append('status', params.status);
    if (params?.protocol) searchParams.append('protocol', params.protocol);
    if (params?.country) searchParams.append('country', params.country);
    if (params?.search) searchParams.append('search', params.search);
    if (params?.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.append('sort_order', params.sort_order);
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));
    const query = searchParams.toString();
    return request<ProxyListResponse>(`/proxy/db/list${query ? `?${query}` : ''}`);
  },

  // 상위 프록시 목록
  top: (limit = 10) => request<Proxy[]>(`/proxy/db/top?limit=${limit}`),

  // 단일 조회 (검증 이력 포함)
  get: (id: number) => request<ProxyDetail>(`/proxy/db/${id}`),

  // 검증 이력 조회
  getHistory: (id: number, limit = 50) =>
    request<{ items: ProxyDetail['check_history']; total: number }>(
      `/proxy/db/${id}/history?limit=${limit}`
    ),

  // 수집 실행 이력
  runs: (limit = 10) => request<ProxyCollectionRun[]>(`/proxy/db/runs?limit=${limit}`),

  // 상태 변경
  updateStatus: (id: number, status: string) =>
    request<Proxy>(`/proxy/db/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status })
    }),

  // 삭제
  delete: (id: number) =>
    request<null>(`/proxy/db/${id}`, {
      method: 'DELETE'
    }),

  // 파일에서 임포트
  import: () =>
    request<ProxyImportResult>('/proxy/db/import', {
      method: 'POST'
    }),

  // 오래된 프록시 정리
  cleanup: (days = 7) =>
    request<{ deleted_count: number }>(`/proxy/db/cleanup?days=${days}`, {
      method: 'POST'
    })
};

// ============================================================
// Proxy Usage API (프록시 사용 이력)
// ============================================================

export interface ProxyUsageListParams {
  schedule_id?: number;
  proxy_host?: string;
  success?: boolean;
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export interface ProxyUsageStatsParams {
  schedule_id?: number;
  hours?: number;
}

export interface RetryHistoryParams {
  schedule_id?: number;
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export interface FailedProxiesParams {
  hours?: number;
  min_failures?: number;
  limit?: number;
}

export const proxyUsageApi = {
  // 통계 조회
  stats: (params?: ProxyUsageStatsParams) => {
    const searchParams = new URLSearchParams();
    if (params?.schedule_id) searchParams.append('schedule_id', String(params.schedule_id));
    if (params?.hours) searchParams.append('hours', String(params.hours));
    const query = searchParams.toString();
    return request<ProxyUsageStatsResponse>(`/proxy-usage/stats${query ? `?${query}` : ''}`);
  },

  // 최근 사용 내역 조회
  recent: (params?: ProxyUsageListParams) => {
    const searchParams = new URLSearchParams();
    if (params?.schedule_id) searchParams.append('schedule_id', String(params.schedule_id));
    if (params?.proxy_host) searchParams.append('proxy_host', params.proxy_host);
    if (params?.success !== undefined) searchParams.append('success', String(params.success));
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    if (params?.limit) searchParams.append('limit', String(params.limit));
    const query = searchParams.toString();
    return request<ProxyUsageLog[]>(`/proxy-usage/recent${query ? `?${query}` : ''}`);
  },

  // 재시도 이력 조회
  retries: (params?: RetryHistoryParams) => {
    const searchParams = new URLSearchParams();
    if (params?.schedule_id) searchParams.append('schedule_id', String(params.schedule_id));
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    if (params?.limit) searchParams.append('limit', String(params.limit));
    const query = searchParams.toString();
    return request<RetryHistoryResponse[]>(`/proxy-usage/retries${query ? `?${query}` : ''}`);
  },

  // 실패 프록시 조회
  failed: (params?: FailedProxiesParams) => {
    const searchParams = new URLSearchParams();
    if (params?.hours) searchParams.append('hours', String(params.hours));
    if (params?.min_failures) searchParams.append('min_failures', String(params.min_failures));
    if (params?.limit) searchParams.append('limit', String(params.limit));
    const query = searchParams.toString();
    return request<Array<{
      proxy_host: string;
      fail_count: number;
      last_error_type: string | null;
      last_failed_at: string;
    }>>(`/proxy-usage/failed${query ? `?${query}` : ''}`);
  },

  // 오래된 로그 정리
  cleanup: (days = 30) =>
    request<ProxyUsageCleanupResult>(`/proxy-usage/cleanup?days=${days}`, {
      method: 'POST'
    })
};
