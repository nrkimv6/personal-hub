/**
 * System API - 시스템, 워커, 이벤트, 팝업, LLM, 에러 관리
 */
import { request, API_BASE, getAuthToken } from './client';
import type {
  SystemStatus,
  QueueItem,
  ActiveTasks,
  Event,
  EventCreate,
  EventUpdate,
  EventListResponse,
  EventListParams,
  EventImportFromInstagram,
  EventImportFromUrlResponse,
  Popup,
  PopupCreate,
  PopupUpdate,
  PopupListResponse,
  PopupListParams,
  PopupImportFromInstagram,
  UncategorizedPost,
  UncategorizedListResponse,
  UncategorizedListParams,
  ReclassifyRequest,
  ReclassifyResponse,
  UnifiedDashboard,
  VideoDownload,
  VideoDownloadCreate,
  VideoDownloadList,
  VideoDownloadStats,
  VideoDownloadBatchCreate,
  VideoDownloadBatchResponse
} from '../types';

// ============================================================
// 시스템 API
// ============================================================

export const systemApi = {
  // 시스템 상태
  status: (options?: RequestInit) => request<SystemStatus>('/system/status', options),

  // 대기열 조회
  queue: (options?: RequestInit) => request<QueueItem[]>('/system/queue', options),

  // 대기열 비우기
  clearQueue: () =>
    request<{ status: string; cleared_count: number }>('/system/queue/clear', {
      method: 'POST'
    }),

  // 수동 정리
  cleanup: () =>
    request<{ status: string; message: string }>('/system/cleanup', {
      method: 'POST'
    }),

  // 활성 태스크
  tasks: () => request<ActiveTasks>('/system/tasks'),

  // 전체 재시작
  restartAll: () =>
    request<{ status: string; stopped_count: number; started_count: number }>(
      '/system/restart-all',
      { method: 'POST' }
    )
};

// ============================================================
// 워커 API
// ============================================================

export const workerApi = {
  // 상태 조회
  status: () => request<{
    pid: number | null;
    status: string;
    start_time: string | null;
    last_heartbeat: string | null;
    active_tasks: number;
    error_message: string | null;
    uptime_seconds: number | null;
    memory_usage_mb: number | null;
    global_pause: boolean;
    paused_at: string | null;
  }>('/worker/status'),

  // 시작
  start: () => request<{ success: boolean; message: string; pid: number | null }>('/worker/start', {
    method: 'POST'
  }),

  // 중지
  stop: () => request<{ success: boolean; message: string; pid: number | null }>('/worker/stop', {
    method: 'POST'
  }),

  // 재시작
  restart: () => request<{ success: boolean; message: string; pid: number | null }>('/worker/restart', {
    method: 'POST'
  }),

  // 전체 모니터링 일시중지
  pause: () => request<{ success: boolean; message: string; pid: number | null }>('/worker/pause', {
    method: 'POST'
  }),

  // 전체 모니터링 재개
  resume: () => request<{ success: boolean; message: string; pid: number | null }>('/worker/resume', {
    method: 'POST'
  }),

  // 로그 조회
  logs: (lines = 100, filter?: string) => {
    const params = new URLSearchParams({ lines: String(lines) });
    if (filter) params.append('filter', filter);
    return request<{ logs: string[]; total_lines: number; file_path: string }>(
      `/worker/logs?${params.toString()}`
    );
  },

  // 헬스 체크
  health: () => request<{
    is_running: boolean;
    is_healthy: boolean;
    details: Record<string, unknown>;
  }>('/worker/health')
};

// ============================================================
// Dashboard API (통합 대시보드)
// ============================================================

export const dashboardApi = {
  // 통합 대시보드 데이터 조회
  unified: () => request<UnifiedDashboard>('/dashboard/unified')
};

// ============================================================
// Event API (독립 이벤트 관리)
// ============================================================

export const eventApi = {
  // 이벤트 목록 조회
  list: (params?: EventListParams) => {
    const searchParams = new URLSearchParams();
    if (params?.event_type) searchParams.append('event_type', params.event_type);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.event_status) searchParams.append('event_status', params.event_status);
    if (params?.deadline_date) searchParams.append('deadline_date', params.deadline_date);
    if (params?.source_type) searchParams.append('source_type', params.source_type);
    if (params?.url_type) searchParams.append('url_type', params.url_type);
    if (params?.is_bookmarked !== undefined) searchParams.append('is_bookmarked', String(params.is_bookmarked));
    if (params?.is_participated !== undefined) searchParams.append('is_participated', String(params.is_participated));
    if (params?.is_offline !== undefined) searchParams.append('is_offline', String(params.is_offline));
    if (params?.include_unknown_period !== undefined) searchParams.append('include_unknown_period', String(params.include_unknown_period));
    if (params?.unknown_period_filter) searchParams.append('unknown_period_filter', params.unknown_period_filter);
    if (params?.search) searchParams.append('search', params.search);
    if (params?.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.append('sort_order', params.sort_order);
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));
    const query = searchParams.toString();
    return request<EventListResponse>(`/events${query ? `?${query}` : ''}`);
  },

  // 날짜별 마감 이벤트 개수 조회
  getDeadlineCounts: (days: number = 6, eventType?: string) => {
    const searchParams = new URLSearchParams();
    searchParams.append('days', String(days));
    if (eventType) searchParams.append('event_type', eventType);
    return request<Record<string, number>>(`/events/deadline-counts?${searchParams.toString()}`);
  },

  // 이벤트 상세 조회
  get: (id: number) => request<Event>(`/events/${id}`),

  // 이벤트 생성
  create: (data: EventCreate) =>
    request<Event>('/events', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 이벤트 수정
  update: (id: number, data: EventUpdate) =>
    request<Event>(`/events/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // 이벤트 삭제
  delete: (id: number) =>
    request<null>(`/events/${id}`, {
      method: 'DELETE'
    }),

  // 북마크 토글
  toggleBookmark: (id: number) =>
    request<Event>(`/events/${id}/bookmark`, {
      method: 'POST'
    }),

  // 참여 완료 토글
  toggleParticipate: (id: number) =>
    request<Event>(`/events/${id}/participate`, {
      method: 'POST'
    }),

  // 오프라인 상태 토글
  toggleOffline: (id: number) =>
    request<{ id: number; is_offline: boolean; message: string }>(`/events/${id}/toggle-offline`, {
      method: 'POST'
    }),

  // Instagram에서 이벤트 가져오기
  importFromInstagram: (data: EventImportFromInstagram) =>
    request<Event>('/events/import-from-instagram', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // URL 중복 확인
  checkDuplicateUrl: (url: string, excludeId?: number) => {
    const searchParams = new URLSearchParams();
    searchParams.append('url', url);
    if (excludeId) searchParams.append('exclude_id', String(excludeId));
    return request<Event | null>(`/events/check-duplicate-url?${searchParams.toString()}`);
  },

  // URL에서 이벤트 가져오기
  importFromUrl: (url: string, autoSave: boolean = false) =>
    request<EventImportFromUrlResponse>('/events/import-from-url', {
      method: 'POST',
      body: JSON.stringify({ url, auto_save: autoSave })
    })
};

// ============================================================
// Popup API (팝업스토어 관리)
// ============================================================

export const popupApi = {
  // 팝업 목록 조회
  list: (params?: PopupListParams) => {
    const searchParams = new URLSearchParams();
    if (params?.popup_status) searchParams.append('popup_status', params.popup_status);
    if (params?.status) searchParams.append('status', params.status);
    if (params?.source_type) searchParams.append('source_type', params.source_type);
    if (params?.is_bookmarked !== undefined) searchParams.append('is_bookmarked', String(params.is_bookmarked));
    if (params?.is_visited !== undefined) searchParams.append('is_visited', String(params.is_visited));
    if (params?.include_unknown_period !== undefined) searchParams.append('include_unknown_period', String(params.include_unknown_period));
    if (params?.unknown_period_filter) searchParams.append('unknown_period_filter', params.unknown_period_filter);
    if (params?.search) searchParams.append('search', params.search);
    if (params?.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.append('sort_order', params.sort_order);
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));
    const query = searchParams.toString();
    return request<PopupListResponse>(`/popups${query ? `?${query}` : ''}`);
  },

  // 팝업 상세 조회
  get: (id: number) => request<Popup>(`/popups/${id}`),

  // 팝업 생성
  create: (data: PopupCreate) =>
    request<Popup>('/popups', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 팝업 수정
  update: (id: number, data: PopupUpdate) =>
    request<Popup>(`/popups/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // 팝업 삭제
  delete: (id: number) =>
    request<null>(`/popups/${id}`, {
      method: 'DELETE'
    }),

  // 북마크 토글
  toggleBookmark: (id: number) =>
    request<{ is_bookmarked: boolean }>(`/popups/${id}/bookmark`, {
      method: 'POST'
    }),

  // 방문 완료 토글
  toggleVisited: (id: number) =>
    request<{ is_visited: boolean }>(`/popups/${id}/visited`, {
      method: 'POST'
    }),

  // Instagram에서 팝업 가져오기
  importFromInstagram: (data: PopupImportFromInstagram) =>
    request<Popup>('/popups/import-from-instagram', {
      method: 'POST',
      body: JSON.stringify(data)
    })
};

// ============================================================
// Uncategorized API (미분류 항목 관리)
// ============================================================

export const uncategorizedApi = {
  // 미분류 목록 조회
  list: (params?: UncategorizedListParams) => {
    const searchParams = new URLSearchParams();
    if (params?.original_tag) searchParams.append('original_tag', params.original_tag);
    if (params?.include_reclassified !== undefined) searchParams.append('include_reclassified', String(params.include_reclassified));
    if (params?.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.append('sort_order', params.sort_order);
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));
    const query = searchParams.toString();
    return request<UncategorizedListResponse>(`/uncategorized${query ? `?${query}` : ''}`);
  },

  // 미분류 상세 조회
  get: (id: number) => request<UncategorizedPost>(`/uncategorized/${id}`),

  // 재분류 (이벤트 또는 팝업으로)
  reclassify: (id: number, data: ReclassifyRequest) =>
    request<ReclassifyResponse>(`/uncategorized/${id}/reclassify`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 미분류 항목 삭제
  delete: (id: number) =>
    request<null>(`/uncategorized/${id}`, {
      method: 'DELETE'
    })
};

// ============================================================
// LLM Request Management API
// ============================================================

export interface LLMRequest {
  id: number;
  caller_type: string;
  caller_id: string;
  status: string;
  requested_by?: string;
  request_source?: string;
  requested_at?: string;
  processed_at?: string;
  result?: Record<string, unknown>;
  error_message?: string;
  retry_count: number;
}

export interface LLMRequestListResponse {
  items: LLMRequest[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface LLMStats {
  total: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
}

export interface LLMWorkerStatus {
  status: 'healthy' | 'warning' | 'unhealthy' | 'no_worker';
  worker_id?: string;
  state?: string;
  processed_count?: number;
  message?: string;
  seconds_since_heartbeat?: number;
}

export interface LLMHistoryStats {
  data: Array<{
    date: string;
    total: number;
    completed: number;
    failed: number;
    pending: number;
  }>;
  summary: {
    total: number;
    completed: number;
    failed: number;
    success_rate: number;
    avg_processing_time_seconds: number;
  };
}

export interface LLMPerformanceStats {
  period_hours: number;
  llm_stats: {
    total_requests: number;
    failed_count: number;
    avg_processing_time: number;
    min_time: number;
    max_time: number;
    p50: number;
    p95: number;
  };
  by_hour: Array<{
    hour: string;
    count: number;
    avg_time: number;
  }>;
  slow_requests: Array<{
    id: number;
    caller_type: string;
    caller_id: string;
    processing_time: number;
    requested_at: string;
  }>;
}

export interface LLMRequestListParams {
  status?: string;
  caller_type?: string;
  requested_by?: string;
  include_deleted?: boolean;
  page?: number;
  page_size?: number;
}

export interface LLMCallerGroup {
  caller_type: string;
  caller_id: string;
  total_count: number;
  completed_count: number;
  failed_count: number;
  pending_count: number;
  has_success: boolean;
  last_status: string;
  last_requested_at: string;
  last_error: string | null;
  request_ids: number[];
  prompt: string;
}

export interface LLMGroupedListResponse {
  items: LLMCallerGroup[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  summary: {
    total_callers: number;
    callers_with_success: number;
    callers_without_success: number;
  };
}

export interface LLMGroupedListParams {
  caller_type?: string;
  only_without_success?: boolean;
  page?: number;
  page_size?: number;
}

export const llmApi = {
  // 요청 목록 조회
  list: (params?: LLMRequestListParams, options?: RequestInit) => {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.append('status', params.status);
    if (params?.caller_type) searchParams.append('caller_type', params.caller_type);
    if (params?.requested_by) searchParams.append('requested_by', params.requested_by);
    if (params?.include_deleted) searchParams.append('include_deleted', String(params.include_deleted));
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));
    const query = searchParams.toString();
    return request<LLMRequestListResponse>(`/llm/requests${query ? `?${query}` : ''}`, options);
  },

  // 단일 요청 조회
  get: (id: number) => request<LLMRequest>(`/llm/requests/${id}`),

  // 요청 취소
  cancel: (id: number) =>
    request<{ success: boolean; message: string }>(`/llm/requests/${id}/cancel`, {
      method: 'POST'
    }),

  // 요청 재시도
  retry: (id: number) =>
    request<{ success: boolean; message: string }>(`/llm/requests/${id}/retry`, {
      method: 'POST'
    }),

  // 요청 삭제
  delete: (id: number, hardDelete = false) => {
    const query = hardDelete ? '?hard_delete=true' : '';
    return request<{ success: boolean; message: string }>(`/llm/requests/${id}${query}`, {
      method: 'DELETE'
    });
  },

  // 일괄 재시도
  batchRetry: (requestIds: number[]) =>
    request<{ success: number; failed: number; skipped: number }>('/llm/requests/batch/retry', {
      method: 'POST',
      body: JSON.stringify({ request_ids: requestIds })
    }),

  // 일괄 삭제
  batchDelete: (requestIds: number[], hardDelete = false) =>
    request<{ deleted: number; skipped: number }>('/llm/requests/batch/delete', {
      method: 'POST',
      body: JSON.stringify({ request_ids: requestIds, hard_delete: hardDelete })
    }),

  // 워커 상태 조회
  getWorkerStatus: (options?: RequestInit) => request<LLMWorkerStatus>('/llm/worker/status', options),

  // 통계 조회
  getStats: (options?: RequestInit) => request<LLMStats>('/llm/stats', options),

  // 이력 통계 조회
  getHistoryStats: (startDate?: string, endDate?: string) => {
    const searchParams = new URLSearchParams();
    if (startDate) searchParams.append('start_date', startDate);
    if (endDate) searchParams.append('end_date', endDate);
    const query = searchParams.toString();
    return request<LLMHistoryStats>(`/llm/history${query ? `?${query}` : ''}`);
  },

  // 호출자별 통계
  getCallerStats: () =>
    request<Record<string, { total: number; pending: number; processing: number; completed: number; failed: number }>>(
      '/llm/stats/by-caller'
    ),

  // 요청 생성
  create: (data: {
    caller_type: string;
    caller_id: string;
    prompt: string;
    requested_by?: string;
    request_source?: string;
  }) =>
    request<LLMRequest>('/llm/requests', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // Cleanup (stale 및 old history 정리)
  cleanup: () =>
    request<{ stale_processing: number; old_history: number }>('/llm/cleanup', {
      method: 'POST'
    }),

  // 성능 분석 통계
  getPerformanceStats: (hours = 24) =>
    request<LLMPerformanceStats>(`/llm/performance?hours=${hours}`),

  // caller_id별 그룹화된 목록 조회
  listGroupedByCaller: (params?: LLMGroupedListParams, options?: RequestInit) => {
    const searchParams = new URLSearchParams();
    if (params?.caller_type) searchParams.append('caller_type', params.caller_type);
    if (params?.only_without_success) searchParams.append('only_without_success', String(params.only_without_success));
    if (params?.page) searchParams.append('page', String(params.page));
    if (params?.page_size) searchParams.append('page_size', String(params.page_size));
    const query = searchParams.toString();
    return request<LLMGroupedListResponse>(`/llm/requests/grouped-by-caller${query ? `?${query}` : ''}`, options);
  },

  // 성공 없는 caller들의 실패 요청 일괄 재시도
  retryFailedCallersWithoutSuccess: (callerType?: string) =>
    request<{ retried: number; callers: number }>('/llm/requests/batch/retry-failed-callers', {
      method: 'POST',
      body: JSON.stringify({ caller_type: callerType || null })
    })
};

// ============================================================
// Error Monitoring API
// ============================================================

export interface ErrorLog {
  id: number;
  created_at: string;
  source: string;
  severity: string;
  error_type: string;
  message: string;
  traceback?: string;
  context?: Record<string, unknown>;
  resolved: boolean;
  resolved_at?: string;
  resolved_by?: string;
  notes?: string;
}

export interface ErrorLogList {
  items: ErrorLog[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ErrorLogStats {
  total_count: number;
  critical_count: number;
  error_count: number;
  warning_count: number;
  resolved_count: number;
  unresolved_count: number;
  resolve_rate: number;
}

export interface ErrorLogSourceStats {
  source: string;
  count: number;
  critical_count: number;
  error_count: number;
  warning_count: number;
}

export interface ErrorLogTypeStats {
  error_type: string;
  count: number;
  last_occurred?: string;
}

export interface ErrorLogHourlyStats {
  hour: number;
  count: number;
  critical_count: number;
  error_count: number;
  warning_count: number;
}

export interface ErrorLogStatsResponse {
  summary: ErrorLogStats;
  by_source: ErrorLogSourceStats[];
  by_type: ErrorLogTypeStats[];
  by_hour: ErrorLogHourlyStats[];
  period_hours: number;
}

export interface ErrorListParams {
  source?: string;
  severity?: string;
  error_type?: string;
  resolved?: boolean;
  date_from?: string;
  date_to?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

export const errorApi = {
  // 에러 목록 조회
  list: (params: ErrorListParams = {}) => {
    const query = new URLSearchParams();
    if (params.source) query.append('source', params.source);
    if (params.severity) query.append('severity', params.severity);
    if (params.error_type) query.append('error_type', params.error_type);
    if (params.resolved !== undefined) query.append('resolved', String(params.resolved));
    if (params.date_from) query.append('date_from', params.date_from);
    if (params.date_to) query.append('date_to', params.date_to);
    if (params.search) query.append('search', params.search);
    if (params.page) query.append('page', String(params.page));
    if (params.page_size) query.append('page_size', String(params.page_size));
    const queryStr = query.toString();
    return request<ErrorLogList>(`/errors${queryStr ? `?${queryStr}` : ''}`);
  },

  // 에러 통계 조회
  stats: (hours = 24) => request<ErrorLogStatsResponse>(`/errors/stats?hours=${hours}`),

  // 소스 목록 조회
  sources: () => request<string[]>('/errors/sources'),

  // 에러 타입 목록 조회
  types: (source?: string) => {
    const query = source ? `?source=${encodeURIComponent(source)}` : '';
    return request<string[]>(`/errors/types${query}`);
  },

  // 에러 상세 조회
  get: (id: number) => request<ErrorLog>(`/errors/${id}`),

  // 에러 해결 처리
  resolve: (id: number, data: { resolved?: boolean; resolved_by?: string; notes?: string }) =>
    request<ErrorLog>(`/errors/${id}/resolve`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    }),

  // 일괄 해결 처리
  resolveBulk: (errorIds: number[], resolvedBy?: string, notes?: string) =>
    request<{ updated: number; error_ids: number[] }>('/errors/resolve-bulk', {
      method: 'POST',
      body: JSON.stringify({ error_ids: errorIds, resolved_by: resolvedBy, notes })
    }),

  // 오래된 에러 정리
  cleanup: (days = 30, resolvedOnly = true) =>
    request<{ deleted: number; cutoff_date: string }>(`/errors/cleanup?days=${days}&resolved_only=${resolvedOnly}`, {
      method: 'DELETE'
    })
};

// ============================================================
// Integrity API (데이터 정합성 검사)
// ============================================================

export interface IntegrityIssue {
  table: string;
  issue_type: string;
  severity: 'critical' | 'warning' | 'info';
  count: number;
  sample_ids: number[];
  description: string;
  auto_fixable: boolean;
}

export interface IntegrityCheckResponse {
  total_issues: number;
  by_severity: {
    critical: number;
    warning: number;
    info: number;
  };
  issues: IntegrityIssue[];
}

export interface DbStatsResponse {
  tables: Record<string, number | null>;
  db_size_bytes: number;
  db_size_mb: number;
}

export interface FixResult {
  table: string;
  issue_type: string;
  description: string;
  fixed: boolean;
  affected_count: number;
  dry_run: boolean;
  error?: string;
}

export interface FixAllResponse {
  total_issues: number;
  fixable_issues: number;
  results: FixResult[];
  dry_run: boolean;
}

export const integrityApi = {
  // 전체 정합성 검사
  check: () => request<IntegrityCheckResponse>('/integrity/check'),

  // DB 통계 조회
  stats: () => request<DbStatsResponse>('/integrity/stats'),

  // 모든 자동 수정 가능한 문제 수정
  fixAll: (dryRun = true) =>
    request<FixAllResponse>(`/integrity/fix?dry_run=${dryRun}`, {
      method: 'POST'
    }),

  // 특정 문제 수정
  fixSpecific: (table: string, issueType: string, dryRun = true) =>
    request<{ fixed: boolean; affected_count: number; dry_run: boolean; error?: string }>(
      `/integrity/fix/${table}/${issueType}?dry_run=${dryRun}`,
      { method: 'POST' }
    )
};

// ============================================================
// Video Download API
// ============================================================

async function requestVideoDownload<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `/api/v1/video-downloads${endpoint}`;
  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers
  };
  const response = await fetch(url, { ...options, headers, credentials: 'include' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || '요청 실패');
  }
  if (response.status === 204) return null as T;
  return response.json();
}

export const videoDownloadApi = {
  // 다운로드 목록 조회
  list: (params?: {
    status?: string;
    download_type?: string;
    page?: number;
    limit?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.status) searchParams.set('status', params.status);
    if (params?.download_type) searchParams.set('download_type', params.download_type);
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    const query = searchParams.toString();
    return requestVideoDownload<VideoDownloadList>(`${query ? `?${query}` : ''}`);
  },

  // 단건 조회
  get: (id: number) =>
    requestVideoDownload<VideoDownload>(`/${id}`),

  // 다운로드 요청 생성
  create: (data: VideoDownloadCreate) =>
    requestVideoDownload<VideoDownload>('', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 다운로드 취소
  cancel: (id: number) =>
    requestVideoDownload<VideoDownload>(`/${id}`, {
      method: 'DELETE'
    }),

  // 통계 조회
  stats: () =>
    requestVideoDownload<VideoDownloadStats>('/stats'),

  // 재시도
  retry: (id: number) =>
    requestVideoDownload<{ success: boolean; message: string }>(`/${id}/retry`, {
      method: 'POST'
    }),

  // 삭제 (completed/failed/cancelled만 가능)
  delete: (id: number) =>
    requestVideoDownload<{ success: boolean; message: string }>(`/${id}/remove`, {
      method: 'DELETE'
    }),

  // 배치 다운로드 요청 생성
  createBatch: (data: VideoDownloadBatchCreate) =>
    requestVideoDownload<VideoDownloadBatchResponse>('/batch', {
      method: 'POST',
      body: JSON.stringify(data)
    })
};
