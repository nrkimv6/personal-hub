/**
 * Activity API client
 * - 문화/체육센터 도메인의 HTTP 호출을 한곳으로 모은다.
 * - /api/v1/activity 를 source-of-truth로 사용한다.
 */

import { request } from './client';

const BASE = '/activity';

function appendParam(
  searchParams: URLSearchParams,
  key: string,
  value: string | number | boolean | null | undefined
): void {
  if (value === undefined || value === null || value === '') return;
  searchParams.append(key, String(value));
}

function buildQuery(
  params: Record<string, string | number | boolean | null | undefined> | undefined
): string {
  if (!params) return '';
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    appendParam(searchParams, key, value);
  }
  const query = searchParams.toString();
  return query ? `?${query}` : '';
}

export interface ActivityCenter {
  id: number;
  name: string;
  center_type: string;
  operator?: string | null;
  region_sido?: string | null;
  region_sigungu?: string | null;
  address?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  phone?: string | null;
  website?: string | null;
  crawl_url?: string | null;
  crawl_method: string;
  crawl_config?: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_crawled_at?: string | null;
  course_count?: number | null;
}

export interface ActivityCenterListResponse {
  items: ActivityCenter[];
  total: number;
}

export interface ActivityCenterListParams {
  region_sido?: string;
  region_sigungu?: string;
  center_type?: string;
  is_active?: boolean;
  keyword?: string;
  page?: number;
  page_size?: number;
  limit?: number;
}

const ACTIVITY_CENTER_TYPE_LABELS: Record<string, string> = {
  public_city: '시립센터',
  public_district: '구립센터',
  public_dong: '동주민센터',
  department: '백화점',
  mart: '마트',
  private: '사설센터',
  // legacy UI labels for pre-migration data
  culture: '문화센터',
  sports: '체육센터',
  youth: '청소년센터',
  welfare: '복지관'
};

export interface ActivityCourse {
  id: number;
  center_id: number;
  source_id?: string | null;
  source_url?: string | null;
  name: string;
  description?: string | null;
  category?: string | null;
  subcategory?: string | null;
  target_age?: string | null;
  level?: string | null;
  capacity?: number | null;
  fee?: number | null;
  material_fee?: number | null;
  fee_note?: string | null;
  registration_start?: string | null;
  registration_end?: string | null;
  course_start?: string | null;
  course_end?: string | null;
  day_of_week?: string | null;
  time_start?: string | null;
  time_end?: string | null;
  total_sessions?: number | null;
  instructor_name?: string | null;
  instructor_bio?: string | null;
  status?: string | null;
  current_enrollment?: number | null;
  collected_at: string;
  source_updated_at?: string | null;
  center_name?: string | null;
  is_registration_open?: boolean | null;
}

export interface ActivityCourseListResponse {
  items: ActivityCourse[];
  total: number;
  page: number;
  page_size: number;
}

export interface ActivityCourseListParams {
  region_sido?: string;
  region_sigungu?: string;
  category?: string;
  target_age?: string;
  keyword?: string;
  day_of_week?: string;
  fee_min?: number;
  fee_max?: number;
  registration_open?: boolean;
  center_id?: number;
  page?: number;
  page_size?: number;
  limit?: number;
}

export interface ActivityWorkerStatus {
  is_running: boolean;
  last_activity: string | null;
  pending_requests: number;
  processing_requests: number;
  recent_runs: number;
}

export interface ActivityCrawlRequest {
  id: number;
  url: string;
  status: string;
  requested_at: string;
  processed_at?: string | null;
  error_message?: string | null;
}

export interface ActivityCrawlRun {
  id: number;
  center_id?: number | null;
  started_at: string;
  completed_at?: string | null;
  status: string;
  courses_found: number;
  courses_new: number;
  courses_updated: number;
  error_message?: string | null;
  center_name?: string | null;
}

export interface ActivityCrawlRunListResponse {
  items: ActivityCrawlRun[];
  total: number;
}

export function formatActivityRegion(center: Pick<ActivityCenter, 'region_sido' | 'region_sigungu'>): string | undefined {
  const parts = [center.region_sido, center.region_sigungu].filter(Boolean);
  return parts.length > 0 ? parts.join(' ') : undefined;
}

export function formatActivityCenterType(type: string): string {
  return ACTIVITY_CENTER_TYPE_LABELS[type] ?? type;
}

export function activityRequest<T>(endpoint: string, options?: RequestInit): Promise<T> {
  return request<T>(`${BASE}${endpoint}`, options);
}

export function listActivityCenters(params?: ActivityCenterListParams, options?: RequestInit) {
  const query = buildQuery(params);
  return activityRequest<ActivityCenterListResponse>(`/centers${query}`, options);
}

export function searchActivityCourses(params?: ActivityCourseListParams, options?: RequestInit) {
  const query = buildQuery(params);
  return activityRequest<ActivityCourseListResponse>(`/courses${query}`, options);
}

export function getActivityWorkerStatus(options?: RequestInit) {
  return activityRequest<ActivityWorkerStatus>('/worker/status', options);
}

export function listActivityRequests(limit = 10, options?: RequestInit) {
  return activityRequest<ActivityCrawlRequest[]>(`/worker/requests?limit=${limit}`, options);
}

export function requestActivityCrawl(centerId: number) {
  return activityRequest<ActivityCrawlRequest>('/worker/request', {
    method: 'POST',
    body: JSON.stringify({ center_id: centerId })
  });
}

export function triggerActivityHubSync() {
  return activityRequest<{ message: string; status: string }>('/crawl/sync-hub', {
    method: 'POST'
  });
}

export function listActivityCrawlRuns(params?: { center_id?: number; status?: string; page?: number; page_size?: number }) {
  const query = buildQuery(params);
  return activityRequest<ActivityCrawlRunListResponse>(`/crawl/runs${query}`);
}

export function getActivityCrawlRun(runId: number) {
  return activityRequest<ActivityCrawlRun>(`/crawl/runs/${runId}`);
}

export const activityApi = {
  listCenters: listActivityCenters,
  listCourses: searchActivityCourses,
  getWorkerStatus: getActivityWorkerStatus,
  listRequests: listActivityRequests,
  requestCrawl: requestActivityCrawl,
  syncToActivityHub: triggerActivityHubSync,
  listCrawlRuns: listActivityCrawlRuns,
  getCrawlRun: getActivityCrawlRun
};
