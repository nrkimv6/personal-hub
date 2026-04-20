/**
 * Instagram/Crawl API - 인스타그램 크롤링 및 수집 관련
 */
import { request, getAuthToken, fetchWithTimeout } from './client';
import type {
  ServiceAccountWithProfile,
  InstagramPost,
  InstagramPostListResponse,
  InstagramCrawlRun,
  InstagramScheduleConfig,
  InstagramScheduleConfigUpdate,
  InstagramStats,
  InstagramTodayScheduleItem,
  InstagramCrawlRequest,
  InstagramWorkerStatus,
  InstagramWorkerHealth,
  InstagramRunListResponse,
  InstagramRunStats,
  InstagramCrawlRunExtended,
  InstagramTag,
  InstagramKeyword,
  InstagramTagCreate,
  InstagramTagUpdate,
  InstagramKeywordCreate,
  InstagramClassifyResult,
  CrawlHistoryResponse,
  CrawlHistoryParams,
  CrawlRequest,
  CrawlRequestCreate,
  CrawlRequestPaginated,
  CrawlSchedule,
  CrawlScheduleCreate,
  CrawlScheduleUpdate,
  CrawlScheduleRepairResponse,
  CrawlScheduleRunPaginated,
  CrawlRunStats,
  UrlParseResponse,
  LLMRequest,
  RunPostsPaginated
} from '../types';

// ============================================================
// Helper: API V2 & Tasks Request Functions
// ============================================================

const API_V2 = '/api/v2';
const API_TASKS = '/api/tasks';

async function requestTasks<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_TASKS}${endpoint}`;

  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers as Record<string, string>
  };

  const response = await fetchWithTimeout(url, {
    ...options,
    headers
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return response.json();
}

async function requestV2<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_V2}${endpoint}`;

  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers
  };

  const response = await fetchWithTimeout(url, { ...options, headers, credentials: 'include' });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return response.json();
}

// ============================================================
// Types for Crawl API
// ============================================================

export interface CrawlUrlRequest {
  url: string;
  service_account_id?: number;
  auto_analyze?: boolean;
  priority?: number;
}

export interface CrawlUrlResponse {
  success: boolean;
  request_id: number;
  url: string;
  url_type: string;
  status: string;
  message: string;
}

export interface UniversalCrawlRequest {
  id: number;
  url: string;
  url_type: string;
  service_account_id?: number;
  status: string;
  requested_by: string;
  requested_at: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  retry_count: number;
  crawled_page_id?: number;
  auto_analyze: boolean;
  priority: number;
  crawled_page?: CrawledPage;
}

export interface CrawledPage {
  id: number;
  url: string;
  url_type: string;
  title?: string;
  description?: string;
  content?: string;
  extracted_data?: Record<string, unknown>;
  og_title?: string;
  og_description?: string;
  og_image?: string;
  crawled_at: string;
  extractor_used?: string;
  is_event?: boolean;
  event_id?: number;
  analysis_result?: Record<string, unknown>;
}

export interface AnalyzePageResponse {
  success: boolean;
  message: string;
  request_id?: number;
}

export interface AnalysisStatusResponse {
  status: string;
  result?: Record<string, unknown>;
  error?: string;
}

export interface CrawlRequestListParams {
  status?: string;
  url_type?: string;
  analysis_status?: string;
  url_search?: string;
  content_search?: string;
  date_from?: string;
  date_to?: string;
  sort_by?: string;
  sort_order?: string;
  page?: number;
  page_size?: number;
}

export interface InstagramPostListParams {
  account?: string;
  date_from?: string;
  date_to?: string;
  posted_from?: string;
  posted_to?: string;
  is_ad?: boolean;
  post_type?: string;
  tags?: string[];
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
  is_active?: boolean;
  search?: string;
  page?: number;
  limit?: number;
}

// ============================================================
// Crawl API v2 (통합 크롤링)
// ============================================================

export const crawlApi = {
  // ============= URL Crawl (auto-detect) =============

  // URL 크롤링 요청 생성 (URL 타입 자동 감지)
  createUrlRequest: (data: CrawlUrlRequest) =>
    requestV2<CrawlUrlResponse>('/crawl/url', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 크롤링 요청 목록 조회 (필터/정렬 지원) - Universal Crawl
  listRequests: (params?: CrawlRequestListParams) => {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.append('status', params.status);
    if (params?.url_type) searchParams.append('url_type', params.url_type);
    if (params?.analysis_status) searchParams.append('analysis_status', params.analysis_status);
    if (params?.url_search) searchParams.append('url_search', params.url_search);
    if (params?.content_search) searchParams.append('content_search', params.content_search);
    if (params?.date_from) searchParams.append('date_from', params.date_from);
    if (params?.date_to) searchParams.append('date_to', params.date_to);
    if (params?.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.append('sort_order', params.sort_order);
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.page_size) searchParams.append('page_size', params.page_size.toString());
    return requestV2<{ items: UniversalCrawlRequest[]; total: number; total_pages: number }>(`/crawl/universal-requests?${searchParams}`);
  },

  // 크롤링 요청 상세 조회 - Universal Crawl
  getUniversalRequest: (id: number) => requestV2<UniversalCrawlRequest>(`/crawl/universal-requests/${id}`),

  // 실패한 요청 재시도 - Universal Crawl
  retryUniversalRequest: (id: number) =>
    requestV2<UniversalCrawlRequest>(`/crawl/universal-requests/${id}/retry`, { method: 'POST' }),

  // ============= Pages =============

  // 크롤링된 페이지 목록 조회
  listPages: (params?: { url_type?: string; is_event?: boolean; page?: number; page_size?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.url_type) searchParams.append('url_type', params.url_type);
    if (params?.is_event !== undefined) searchParams.append('is_event', params.is_event.toString());
    if (params?.page) searchParams.append('page', params.page.toString());
    if (params?.page_size) searchParams.append('page_size', params.page_size.toString());
    return requestV2<{ items: CrawledPage[]; total: number }>(`/crawl/pages?${searchParams}`);
  },

  // 크롤링된 페이지 상세 조회
  getPage: (id: number) => requestV2<CrawledPage>(`/crawl/pages/${id}`),

  // 페이지 AI 분석 요청
  analyzePage: (pageId: number) =>
    requestV2<AnalyzePageResponse>(`/crawl/pages/${pageId}/analyze`, { method: 'POST' }),

  // 페이지 AI 분석 상태 조회
  getAnalysisStatus: (pageId: number) =>
    requestV2<AnalysisStatusResponse>(`/crawl/pages/${pageId}/analysis`),

  // ============= Simple Requests =============

  // 단건 요청 생성 (단순 - URL 타입 직접 지정)
  createRequest: (data: CrawlRequestCreate) =>
    requestV2<CrawlRequest>('/crawl/requests', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 요청 목록 조회 (단순)
  getRequests: (params?: {
    page?: number;
    limit?: number;
    url_type?: string;
    status?: string;
    requested_by?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.url_type) searchParams.set('url_type', params.url_type);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.requested_by) searchParams.set('requested_by', params.requested_by);
    const query = searchParams.toString();
    return requestV2<CrawlRequestPaginated>(`/crawl/requests${query ? `?${query}` : ''}`);
  },

  // 요청 상세 조회 (단순)
  getRequest: (requestId: number) =>
    requestV2<CrawlRequest>(`/crawl/requests/${requestId}`),

  // 실패한 요청 재시도 (단순)
  retryRequest: (requestId: number) =>
    requestV2<CrawlRequest>(`/crawl/requests/${requestId}/retry`, {
      method: 'POST'
    }),

  // ============= Schedules (moved to /api/tasks) =============

  // 스케줄 생성
  createSchedule: (data: CrawlScheduleCreate) =>
    requestTasks<CrawlSchedule>('/schedules', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 스케줄 목록 조회
  getSchedules: (params?: {
    target_type?: string;
    enabled_only?: boolean;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.target_type) searchParams.set('target_type', params.target_type);
    if (params?.enabled_only !== undefined) searchParams.set('enabled_only', params.enabled_only.toString());
    const query = searchParams.toString();
    return requestTasks<CrawlSchedule[]>(`/schedules${query ? `?${query}` : ''}`);
  },

  // 스케줄 상세 조회
  getSchedule: (scheduleId: number) =>
    requestTasks<CrawlSchedule>(`/schedules/${scheduleId}`),

  // 스케줄 업데이트
  updateSchedule: (scheduleId: number, data: CrawlScheduleUpdate) =>
    requestTasks<CrawlSchedule>(`/schedules/${scheduleId}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // legacy placeholder repair preview
  previewLegacyPlaceholderRepair: () =>
    requestTasks<CrawlScheduleRepairResponse>('/schedules/repair-legacy-placeholder', {
      method: 'POST'
    }),

  // legacy placeholder repair apply
  applyLegacyPlaceholderRepair: () =>
    requestTasks<CrawlScheduleRepairResponse>('/schedules/repair-legacy-placeholder/apply', {
      method: 'POST'
    }),

  // 스케줄 활성화/비활성화
  toggleSchedule: (scheduleId: number, enabled: boolean) =>
    requestTasks<{ success: boolean; enabled: boolean }>(`/schedules/${scheduleId}/toggle?enabled=${enabled}`, {
      method: 'POST'
    }),

  // ============= Schedule Runs (moved to /api/tasks) =============

  // 스케줄 실행 이력 조회
  getScheduleRuns: (scheduleId: number, params?: {
    page?: number;
    limit?: number;
    status?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.status) searchParams.set('status', params.status);
    const query = searchParams.toString();
    return requestTasks<CrawlScheduleRunPaginated>(`/schedules/${scheduleId}/runs${query ? `?${query}` : ''}`);
  },

  // 스케줄 실행 통계 조회
  getScheduleStats: (scheduleId: number, days?: number) =>
    requestTasks<CrawlRunStats>(`/schedules/${scheduleId}/stats${days ? `?days=${days}` : ''}`),

  // 실행에서 수집된 포스트 조회
  getRunPosts: (scheduleId: number, runId: number, params?: {
    page?: number;
    limit?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    const query = searchParams.toString();
    return requestTasks<RunPostsPaginated>(`/schedules/${scheduleId}/runs/${runId}/posts${query ? `?${query}` : ''}`);
  },

  // 전체 실행 이력 조회
  getAllRuns: (params?: {
    page?: number;
    limit?: number;
    status?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.status) searchParams.set('status', params.status);
    const query = searchParams.toString();
    return requestTasks<CrawlScheduleRunPaginated>(`/runs${query ? `?${query}` : ''}`);
  }
};

// ============================================================
// Collect API (수집 관리)
// ============================================================

export interface CollectedPost {
  id: number;
  source_type: 'instagram' | 'web';
  source_id: number;
  title: string | null;
  content: string | null;
  thumbnail: string | null;
  url: string;
  url_type: string;
  created_at: string;
  classification: string | null;
  // Instagram 전용
  shortcode?: string;
  account_name?: string;
  is_active?: boolean;
  tags?: string[];
  llm_status?: 'pending' | 'processing' | 'completed' | 'failed' | null;
  // Web 전용
  extractor_used?: string;
  is_event?: boolean;
}

export interface CollectedPostList {
  items: CollectedPost[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface CollectedPostFilters {
  source_type?: string;
  url_type?: string;
  classification?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

export interface CrawlHistoryItem {
  id: number;
  history_type: 'request' | 'schedule_run' | 'google_search';
  source_type: 'instagram' | 'web' | 'google_search' | 'activity' | 'writing' | 'report';
  status: 'pending' | 'processing' | 'completed' | 'failed';
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  stop_reason?: string | null;
  // Request / Google Search 전용
  url?: string;
  url_type?: string;
  request_type?: string;
  requested_by?: string;
  // Schedule Run / Google Search 전용
  schedule_id?: number;
  schedule_name?: string;
  collected_count: number;
  saved_count: number;
  created_count: number;  // 신규 추가
  updated_count: number;  // 업데이트
  unchanged_count: number;  // 중복 (변경없음)
}

export interface CrawlHistoryList {
  items: CrawlHistoryItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface CrawlHistoryFilters {
  source_type?: string;
  status?: string;
  period?: string;
  page?: number;
  limit?: number;
}

export const collectApi = {
  // ============== 기존 통합 기능 ==============

  // 통합 게시물 목록 조회
  getPosts: (params?: CollectedPostFilters) => {
    const searchParams = new URLSearchParams();
    if (params?.source_type) searchParams.set('source_type', params.source_type);
    if (params?.url_type) searchParams.set('url_type', params.url_type);
    if (params?.classification) searchParams.set('classification', params.classification);
    if (params?.search) searchParams.set('search', params.search);
    if (params?.date_from) searchParams.set('date_from', params.date_from);
    if (params?.date_to) searchParams.set('date_to', params.date_to);
    if (params?.is_active !== undefined) searchParams.set('is_active', params.is_active.toString());
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    const query = searchParams.toString();
    return request<CollectedPostList>(`/collect/posts${query ? `?${query}` : ''}`);
  },

  // URL 타입 목록 조회
  getUrlTypes: () => request<string[]>('/collect/url-types'),

  // 크롤링 이력 조회
  getHistory: (params?: CrawlHistoryFilters) => {
    const searchParams = new URLSearchParams();
    if (params?.source_type) searchParams.set('source_type', params.source_type);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.period) searchParams.set('period', params.period);
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    const query = searchParams.toString();
    return request<CrawlHistoryList>(`/collect/history${query ? `?${query}` : ''}`);
  },

  // 스케줄 목록 조회
  getSchedules: () => request<CrawlSchedule[]>('/collect/schedules'),

  // 스케줄 활성화/비활성화
  toggleSchedule: (scheduleId: number, enabled: boolean) =>
    request<{ success: boolean; enabled: boolean }>(`/collect/schedules/${scheduleId}/toggle?enabled=${enabled}`, {
      method: 'POST',
    }),

  // 스케줄 즉시 실행
  runSchedule: (scheduleId: number) =>
    request<{ success: boolean; message: string; request_id?: number }>(`/collect/schedules/${scheduleId}/run`, {
      method: 'POST',
    }),

  // 스케줄 생성
  createSchedule: (data: {
    target_type: string;
    target_config?: Record<string, unknown>;
    display_name?: string;
    schedule_type?: string;
    schedule_value?: Record<string, unknown>;
  }) =>
    request<CrawlSchedule>('/collect/schedules', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 스케줄 삭제
  deleteSchedule: (scheduleId: number, deleteRuns: boolean = false) =>
    request<{ success: boolean; message: string; deleted_runs: number }>(
      `/collect/schedules/${scheduleId}?delete_runs=${deleteRuns}`,
      { method: 'DELETE' }
    ),

  // 스케줄 상세 조회
  getScheduleDetail: (scheduleId: number) =>
    request<CrawlSchedule & {
      target_config?: Record<string, unknown>;
      schedule_value?: Record<string, unknown>;
      saved_search?: {
        id: number;
        name: string;
        query: string;
        date_filter: string | null;
        max_pages: number;
        search_params: Record<string, unknown> | null;
      };
    }>(`/collect/schedules/${scheduleId}`),

  // 스케줄 수정
  updateSchedule: (scheduleId: number, data: {
    display_name?: string;
    schedule_value?: Record<string, unknown>;
    google_search_params?: Record<string, unknown>;
    target_config?: Record<string, unknown> | null;
  }) =>
    request<CrawlSchedule>(`/collect/schedules/${scheduleId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  previewLegacyPlaceholderRepair: () =>
    request<CrawlScheduleRepairResponse>('/collect/schedules/repair-legacy-placeholder', {
      method: 'POST'
    }),

  applyLegacyPlaceholderRepair: () =>
    request<CrawlScheduleRepairResponse>('/collect/schedules/repair-legacy-placeholder/apply', {
      method: 'POST'
    }),

  // Google 저장된 검색 목록 조회
  getSavedSearches: () =>
    request<{ id: number; name: string; query: string; is_favorite: boolean }[]>('/google/saved'),

  // ============== Instagram 통합 기능 (from instagramApi) ==============

  // 계정 관리
  getAccounts: () => request<ServiceAccountWithProfile[]>('/instagram/accounts'),

  // 게시물 CRUD (Instagram)
  getPost: (id: number) => request<InstagramPost>(`/instagram/posts/${id}`),

  deletePost: (id: number) =>
    request<{ message: string }>(`/instagram/posts/${id}`, {
      method: 'DELETE'
    }),

  updatePost: (id: number, data: { tag_ids?: number[] }) =>
    request<InstagramPost>(`/instagram/posts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  toggleActive: (id: number, isActive: boolean) =>
    request<InstagramPost>(`/instagram/posts/${id}/active?is_active=${isActive}`, {
      method: 'PATCH'
    }),

  // 일괄 작업
  batchDelete: (postIds: number[]) =>
    request<{ success: boolean; deleted: number; total: number }>('/instagram/posts/batch/delete', {
      method: 'POST',
      body: JSON.stringify({ post_ids: postIds })
    }),

  batchDeactivate: (postIds: number[]) =>
    request<{ success: boolean; updated: number; total: number }>('/instagram/posts/batch/deactivate', {
      method: 'POST',
      body: JSON.stringify({ post_ids: postIds })
    }),

  batchAnalyze: (postIds: number[]) =>
    request<{ success: boolean; created_count: number; request_ids: number[]; total: number }>('/instagram/posts/batch/analyze', {
      method: 'POST',
      body: JSON.stringify({ post_ids: postIds })
    }),

  // AI 분석
  requestLlmAnalysisSingle: (postId: number) =>
    request<{ success: boolean; request_id: number; post_id: number; message: string }>(`/instagram/posts/${postId}/analyze`, {
      method: 'POST'
    }),

  getLlmResult: (postId: number) =>
    request<LLMRequest | null>(`/instagram/llm/posts/${postId}`),

  // 크롤링 관련
  recrawlPost: (postId: number) =>
    request<InstagramCrawlRequest>(`/instagram/posts/${postId}/recrawl`, {
      method: 'POST'
    }),

  crawlByUrl: (url: string, accountId: number) =>
    request<InstagramCrawlRequest>(`/instagram/posts/crawl-url`, {
      method: 'POST',
      body: JSON.stringify({ url, service_account_id: accountId })
    }),

  crawlByGenericUrl: (url: string, accountId: number, options?: { maxPosts?: number; scrollCount?: number }) =>
    request<InstagramCrawlRequest>(`/instagram/crawl/url`, {
      method: 'POST',
      body: JSON.stringify({
        url,
        service_account_id: accountId,
        max_posts: options?.maxPosts ?? 20,
        scroll_count: options?.scrollCount ?? 3
      })
    }),

  // 복수 URL 배치 크롤링 (모든 URL 타입 지원)
  crawlByUrls: (urls: string[], options?: { serviceAccountId?: number; autoAnalyze?: boolean; priority?: number }) =>
    requestV2<{ created: number; skipped: number; errors: string[]; request_ids: number[] }>(`/crawl/urls`, {
      method: 'POST',
      body: JSON.stringify({
        urls,
        service_account_id: options?.serviceAccountId ?? null,
        auto_analyze: options?.autoAnalyze ?? true,
        priority: options?.priority ?? 0
      })
    }),

  parseUrl: (url: string) =>
    request<UrlParseResponse>('/instagram/url/parse', {
      method: 'POST',
      body: JSON.stringify({ url })
    }),

  // Instagram 스케줄 관리
  getInstagramSchedule: () => request<InstagramScheduleConfig>('/instagram/schedule'),

  updateInstagramSchedule: (data: InstagramScheduleConfigUpdate) =>
    request<InstagramScheduleConfig>('/instagram/schedule', {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  todaySchedule: (options?: RequestInit) => request<InstagramTodayScheduleItem[]>('/instagram/schedule/today', options),

  requestManualCrawl: (accountId: number) =>
    request<InstagramCrawlRequest>(
      `/instagram/crawl/manual?service_account_id=${accountId}`,
      { method: 'POST' }
    ),

  getCrawlRequests: (params?: { limit?: number; service_account_id?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.append('limit', String(params.limit));
    if (params?.service_account_id) searchParams.append('service_account_id', String(params.service_account_id));
    const query = searchParams.toString();
    return request<InstagramCrawlRequest[]>(`/instagram/crawl/requests${query ? `?${query}` : ''}`);
  },

  getPendingRequests: (limit?: number) => {
    const query = limit ? `?limit=${limit}` : '';
    return request<InstagramCrawlRequest[]>(`/instagram/crawl/requests/pending${query}`);
  },

  // 크롤링 이력 (Instagram 전용)
  getInstagramCrawlHistory: (params?: CrawlHistoryParams) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.limit) searchParams.append('limit', String(params.limit));
    if (params?.request_type) searchParams.append('request_type', params.request_type);
    if (params?.requested_by) searchParams.append('requested_by', params.requested_by);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.period) searchParams.append('period', params.period);
    if (params?.service_account_id) searchParams.append('service_account_id', String(params.service_account_id));
    const query = searchParams.toString();
    return request<CrawlHistoryResponse>(`/instagram/crawl/history${query ? `?${query}` : ''}`);
  },

  retryCrawlRequest: (requestId: number) =>
    request<InstagramCrawlRequest>(`/instagram/crawl/history/${requestId}/retry`, { method: 'POST' }),

  // 로그인 관리
  openLoginBrowser: (accountId: number) =>
    request<{ success: boolean; message: string; service_account_id: number; account_name: string }>(
      `/instagram/login/open-browser?service_account_id=${accountId}`,
      { method: 'POST' }
    ),

  checkLoginStatus: (accountId: number) =>
    request<{ success: boolean; message: string; service_account_id: number; account_name: string; is_logged_in: boolean }>(
      `/instagram/login/check?service_account_id=${accountId}`,
      { method: 'POST' }
    ),

  // 워커 상태
  getWorkerStatus: (options?: RequestInit) => request<InstagramWorkerStatus | null>('/instagram/worker/status', options),
  getWorkerHealth: (options?: RequestInit) => request<InstagramWorkerHealth>('/instagram/worker/health', options),

  // 실행 기록 (Instagram runs)
  runs: async (params?: { limit?: number; service_account_id?: number }, options?: RequestInit): Promise<InstagramCrawlRun[]> => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.append('limit', String(params.limit));
    if (params?.service_account_id) searchParams.append('service_account_id', String(params.service_account_id));
    const query = searchParams.toString();
    const response = await request<InstagramRunListResponse>(`/instagram/runs${query ? `?${query}` : ''}`, options);
    return response.runs;
  },

  getRunsPaginated: (params?: {
    page?: number;
    limit?: number;
    period?: string;
    status?: string;
    service_account_id?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.limit) searchParams.append('limit', String(params.limit));
    if (params?.period) searchParams.append('period', params.period);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.service_account_id) searchParams.append('service_account_id', String(params.service_account_id));
    const query = searchParams.toString();
    return request<InstagramRunListResponse>(`/instagram/runs${query ? `?${query}` : ''}`);
  },

  getRunStats: (days = 7) =>
    request<InstagramRunStats>(`/instagram/runs/stats?days=${days}`),

  getRunDetail: (runId: number) =>
    request<InstagramCrawlRunExtended>(`/instagram/runs/${runId}`),

  getRunPosts: (runId: number, params?: { page?: number; limit?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.limit) searchParams.append('limit', String(params.limit));
    const query = searchParams.toString();
    return request<InstagramPostListResponse>(`/instagram/runs/${runId}/posts${query ? `?${query}` : ''}`);
  },

  // 통계
  stats: (options?: RequestInit) => request<InstagramStats>('/instagram/stats', options),

  // ============== 태그 관리 (from instagramTagApi) ==============

  tags: {
    getTags: (includeInactive = false) => {
      const query = includeInactive ? '?include_inactive=true' : '';
      return request<InstagramTag[]>(`/instagram/tags${query}`);
    },

    getTag: (tagId: number) => request<InstagramTag>(`/instagram/tags/${tagId}`),

    createTag: (data: InstagramTagCreate) =>
      request<InstagramTag>('/instagram/tags', {
        method: 'POST',
        body: JSON.stringify(data)
      }),

    updateTag: (tagId: number, data: InstagramTagUpdate) =>
      request<InstagramTag>(`/instagram/tags/${tagId}`, {
        method: 'PUT',
        body: JSON.stringify(data)
      }),

    deleteTag: (tagId: number) =>
      request<{ success: boolean; message: string }>(`/instagram/tags/${tagId}`, {
        method: 'DELETE'
      }),

    getKeywords: (tagId: number, includeInactive = false) => {
      const query = includeInactive ? '?include_inactive=true' : '';
      return request<InstagramKeyword[]>(`/instagram/tags/${tagId}/keywords${query}`);
    },

    addKeyword: (tagId: number, data: InstagramKeywordCreate) =>
      request<InstagramKeyword>(`/instagram/tags/${tagId}/keywords`, {
        method: 'POST',
        body: JSON.stringify(data)
      }),

    addKeywordsBulk: (tagId: number, keywords: string[]) =>
      request<{ success: boolean; added: number }>(`/instagram/tags/${tagId}/keywords/bulk`, {
        method: 'POST',
        body: JSON.stringify({ keywords })
      }),

    deleteKeyword: (keywordId: number) =>
      request<{ success: boolean; message: string }>(`/instagram/keywords/${keywordId}`, {
        method: 'DELETE'
      }),

    toggleKeyword: (keywordId: number) =>
      request<{ success: boolean; is_active: boolean }>(`/instagram/keywords/${keywordId}/toggle`, {
        method: 'PATCH'
      }),

    classifyPosts: (postIds: number[]) =>
      request<InstagramClassifyResult>('/instagram/classify', {
        method: 'POST',
        body: JSON.stringify({ post_ids: postIds })
      }),

    reclassifyAll: () =>
      request<InstagramClassifyResult>('/instagram/classify/all', {
        method: 'POST'
      }),

    getPostTags: (postId: number) =>
      request<{ post_id: number; tags: string[] }>(`/instagram/posts/${postId}/tags`),
  },
};
