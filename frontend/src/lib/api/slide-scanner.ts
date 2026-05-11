import { API_BASE, fetchWithTimeout, getAuthToken, request } from './client';

const BASE = '/ss';

export type SlideStatus = 'PENDING' | 'REVIEWED' | 'DONE';
export type AspectRatioValue = 'AUTO' | '16:9' | '4:3';
export interface SlideFilterOptions {
  white_balance: boolean;
  contrast: number;
  document_mode: boolean;
}

export const DEFAULT_SLIDE_FILTERS: SlideFilterOptions = {
  white_balance: false,
  contrast: 1.0,
  document_mode: false
};

export interface SlidePoint {
  x: number;
  y: number;
}

export interface SlideUploadResponse {
  id: number;
  status: SlideStatus;
  points: SlidePoint[];
  thumbnail_base64?: string | null;
}

export interface SlideDetailResponse {
  id: number;
  file_name: string;
  status: SlideStatus;
  tag?: string | null;
  captured_at?: string | null;
  source_app?: string | null;
  aspect_ratio?: Exclude<AspectRatioValue, 'AUTO'> | null;
  filters_applied?: SlideFilterOptions | null;
  extracted_text?: string | null;
  points: SlidePoint[];
  inherited_points?: SlidePoint[] | null;
  has_result: boolean;
  thumbnail_base64?: string | null;
}

export interface SlideListItem {
  id: number;
  file_name: string;
  file_path: string;
  result_path?: string | null;
  status: SlideStatus;
  tag?: string | null;
  aspect_ratio?: Exclude<AspectRatioValue, 'AUTO'> | null;
  filters_applied?: SlideFilterOptions | null;
  extracted_text?: string | null;
  captured_at?: string | null;
  source_app?: string | null;
  is_archived: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  thumbnail_url?: string;
}

export interface SlideListResponse {
  slides: SlideListItem[];
  skip: number;
  limit: number;
  total: number;
  has_more: boolean;
}

export interface ScanFolderResponse {
  folder_path: string;
  recursive: boolean;
  scanned: number;
  created: number;
  skipped: number;
  failed: number;
  errors: Array<{ file_path: string; error: string }>;
}

export interface SlideTransformResponse {
  id: number;
  status: 'DONE';
  aspect_ratio?: Exclude<AspectRatioValue, 'AUTO'> | null;
  filters_applied?: SlideFilterOptions | null;
  result_path: string;
  result_url: string;
}

export interface SlideReviewResponse {
  id: number;
  status: 'REVIEWED';
}

export interface SlideUpdateResponse {
  id: number;
  status: SlideStatus;
  tag?: string | null;
  updated_at?: string | null;
}

export interface SlideOcrResponse {
  id: number;
  extracted_text: string;
}

export interface BatchTransformResponse {
  requested: number;
  done: number;
  failed: number;
  skipped: number;
  failures: Array<{ id: number; reason: string }>;
}

export interface ArchiveSlidesResponse {
  archive_path?: string | null;
  requested: number;
  archived: number;
  skipped: Array<{ id: number; reason: string }>;
}

export interface PdfExportResponse {
  blob: Blob;
  filename: string;
}

export interface SlideScannerTaskAcceptedResponse {
  task_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
}

export interface SlideScannerTaskStatusResponse<T = Record<string, unknown>> {
  task_id: string;
  kind: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  result?: T | null;
  error_message?: string | null;
}

export interface SlideScannerSettings {
  scan_path?: string | null;
  output_path: string;
  archive_path: string;
}

export interface MobileSyncDevice {
  serial: string;
  state: string;
  is_online: boolean;
  model?: string | null;
  device?: string | null;
  product?: string | null;
  transport_id?: string | null;
  alias?: string | null;
}

export interface MobileSyncDevicesResponse {
  devices: MobileSyncDevice[];
  total: number;
  online: number;
}

export interface MobileSyncStatusResponse {
  is_running: boolean;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  last_result?: Record<string, unknown> | null;
  last_error?: string | null;
}

export interface MobileSyncRunResponse extends Record<string, unknown> {
  status: string;
  message?: string;
}

export type MobileApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED';
export type MobileDeleteStatus = 'PENDING' | 'DONE' | 'FAILED';
export type MobileHandoffStatus = 'PENDING' | 'DONE' | 'FAILED';

export interface MobileReviewStateSnapshot {
  approval_status: MobileApprovalStatus;
  remote_delete_status: MobileDeleteStatus;
  handoff_status: MobileHandoffStatus;
  slide_id?: number | null;
  can_approve: boolean;
  can_remote_delete: boolean;
  can_handoff: boolean;
  can_open_editor: boolean;
}

export interface MobileReviewItem extends MobileReviewStateSnapshot {
  id: number;
  device_id: string;
  device_serial: string;
  device_alias?: string | null;
  original_filename: string;
  source_uri: string;
  pc_inbox_path: string;
  captured_at_utc: string;
  local_cleanup_status: 'PENDING' | 'DONE' | 'FAILED';
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  image_url: string;
}

export interface MobileReviewItemsResponse {
  items: MobileReviewItem[];
  skip: number;
  limit: number;
  total: number;
  has_more: boolean;
}

export interface MobileReviewUpdateResponse {
  id: number;
  approval_status: MobileApprovalStatus;
  remote_delete_status: MobileDeleteStatus;
  handoff_status: MobileHandoffStatus;
  slide_id?: number | null;
  can_approve: boolean;
  can_remote_delete: boolean;
  can_handoff: boolean;
  can_open_editor: boolean;
  reason?: string;
}

export interface MobileRemoteDeleteResponse {
  status: 'done' | 'failed' | 'skipped_done';
  item_id: number;
  results: Record<string, boolean>;
  error?: string;
  approval_status: MobileApprovalStatus;
  remote_delete_status: MobileDeleteStatus;
  handoff_status: MobileHandoffStatus;
  slide_id?: number | null;
  can_approve: boolean;
  can_remote_delete: boolean;
  can_handoff: boolean;
  can_open_editor: boolean;
}

export interface MobileHandoffResponse {
  item_id: number;
  slide_id: number;
  slide_url: string;
  approval_status: MobileApprovalStatus;
  remote_delete_status: MobileDeleteStatus;
  handoff_status: MobileHandoffStatus;
  can_approve: boolean;
  can_remote_delete: boolean;
  can_handoff: boolean;
  can_open_editor: boolean;
}

function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function normalizeFilterPayload(filters?: SlideFilterOptions | null): SlideFilterOptions | null {
  if (!filters) return null;

  const normalized: SlideFilterOptions = {
    white_balance: Boolean(filters.white_balance),
    contrast: Number.isFinite(filters.contrast)
      ? Math.max(0.5, Math.min(2.0, Number(filters.contrast)))
      : 1.0,
    document_mode: Boolean(filters.document_mode)
  };
  if (
    !normalized.white_balance &&
    !normalized.document_mode &&
    Math.abs(normalized.contrast - 1.0) < 1e-6
  ) {
    return null;
  }
  return normalized;
}

function parseContentDispositionFilename(value: string | null): string | null {
  if (!value) return null;

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }

  const basicMatch = value.match(/filename=\"?([^\";]+)\"?/i);
  if (!basicMatch?.[1]) return null;
  return basicMatch[1];
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (typeof detail === 'string' && detail.trim()) {
        message = detail;
      } else if (detail && typeof detail === 'object') {
        const stage = typeof detail.stage === 'string' ? `[${detail.stage}] ` : '';
        const detailMessage =
          typeof detail.message === 'string'
            ? detail.message
            : typeof detail.error === 'string'
              ? detail.error
              : JSON.stringify(detail);
        message = `${stage}${detailMessage}`;
      } else if (typeof body?.message === 'string' && body.message.trim()) {
        message = body.message;
      }
    } catch {
      // ignore JSON parsing errors
    }
    throw new Error(message || '요청 실패');
  }
  return response.json() as Promise<T>;
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runTask<T>(
  endpoint: string,
  body?: unknown,
  timeoutMs = 30000
): Promise<T> {
  const response = await fetchWithTimeout(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...authHeaders()
    },
    credentials: 'include',
    body: body === undefined ? undefined : JSON.stringify(body)
  }, timeoutMs);
  const accepted = await parseResponse<SlideScannerTaskAcceptedResponse>(response);

  for (let attempt = 0; attempt < 180; attempt += 1) {
    const status = await request<SlideScannerTaskStatusResponse<T>>(`${BASE}/tasks/${accepted.task_id}`);
    if (status.status === 'completed') return (status.result ?? {}) as T;
    if (status.status === 'failed') throw new Error(status.error_message || '작업이 실패했습니다.');
    await wait(1000);
  }
  throw new Error('작업 상태 확인 시간이 초과되었습니다.');
}

async function uploadSlide(
  file: File,
  options?: { sourceApp?: string; capturedAt?: string }
): Promise<SlideUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  if (options?.sourceApp) form.append('source_app', options.sourceApp);
  if (options?.capturedAt) form.append('captured_at', options.capturedAt);

  const response = await fetchWithTimeout(`${API_BASE}${BASE}/slides/upload`, {
    method: 'POST',
    body: form,
    headers: authHeaders(),
    credentials: 'include'
  });
  return parseResponse<SlideUploadResponse>(response);
}

function getSlide(slideId: number): Promise<SlideDetailResponse> {
  return request<SlideDetailResponse>(`${BASE}/slides/${slideId}`);
}

function getSlideWithInherited(slideId: number): Promise<
  SlideDetailResponse & { inherited_points?: SlidePoint[] | null }
> {
  return request<SlideDetailResponse>(`${BASE}/slides/${slideId}`);
}

function transformSlide(
  slideId: number,
  points: SlidePoint[],
  aspectRatio?: AspectRatioValue,
  filters?: SlideFilterOptions | null
): Promise<SlideTransformResponse> {
  return runTask<SlideTransformResponse>(`${BASE}/slides/${slideId}/transform/tasks`, {
    points,
    aspect_ratio: aspectRatio && aspectRatio !== 'AUTO' ? aspectRatio : null,
    filters: normalizeFilterPayload(filters)
  });
}

function getSlideImageUrl(slideId: number): string {
  return `${API_BASE}${BASE}/slides/${slideId}/image`;
}

function reviewSlide(slideId: number, points: SlidePoint[]): Promise<SlideReviewResponse> {
  return request<SlideReviewResponse>(`${BASE}/slides/${slideId}/review`, {
    method: 'POST',
    body: JSON.stringify({ points })
  });
}

function ocrSlide(slideId: number, languages?: string[]): Promise<SlideOcrResponse> {
  return runTask<SlideOcrResponse>(`${BASE}/slides/${slideId}/ocr/tasks`, {
    languages: languages?.length ? languages : null
  });
}

function getSlideThumbnailUrl(slideId: number): string {
  return `${API_BASE}${BASE}/slides/${slideId}/thumbnail`;
}

function getSlideResultUrl(slideId: number): string {
  return `${API_BASE}${BASE}/slides/${slideId}/result`;
}

function getSlideList(params?: {
  skip?: number;
  limit?: number;
  status?: SlideStatus | 'ALL';
  search?: string;
  tag?: string;
}): Promise<SlideListResponse> {
  const query = new URLSearchParams();
  if (typeof params?.skip === 'number') query.set('skip', String(params.skip));
  if (typeof params?.limit === 'number') query.set('limit', String(params.limit));
  if (params?.status && params.status !== 'ALL') query.set('status', params.status);
  if (params?.search?.trim()) query.set('search', params.search.trim());
  if (params?.tag?.trim()) query.set('tag', params.tag.trim());

  const qs = query.toString();
  const path = qs ? `${BASE}/slides?${qs}` : `${BASE}/slides`;
  return request<SlideListResponse>(path);
}

function updateSlide(slideId: number, payload: { tag?: string | null }): Promise<SlideUpdateResponse> {
  return request<SlideUpdateResponse>(`${BASE}/slides/${slideId}`, {
    method: 'PUT',
    body: JSON.stringify({
      tag: payload.tag ?? null
    })
  });
}

function getTags(): Promise<{ tags: string[] }> {
  return request<{ tags: string[] }>(`${BASE}/tags`);
}

function scanFolder(
  folderPath: string,
  options?: { recursive?: boolean; limit?: number | null }
): Promise<ScanFolderResponse> {
  return request<ScanFolderResponse>(`${BASE}/scan`, {
    method: 'POST',
    body: JSON.stringify({
      folder_path: folderPath,
      recursive: options?.recursive ?? true,
      limit: options?.limit ?? null
    })
  });
}

function batchTransform(
  ids: number[],
  options?: { aspectRatio?: AspectRatioValue | null; filters?: SlideFilterOptions | null }
): Promise<BatchTransformResponse> {
  return runTask<BatchTransformResponse>(`${BASE}/slides/batch-transform/tasks`, {
    ids,
    aspect_ratio:
      options?.aspectRatio && options.aspectRatio !== 'AUTO' ? options.aspectRatio : null,
    filters: normalizeFilterPayload(options?.filters)
  });
}

function archiveSlides(ids: number[]): Promise<ArchiveSlidesResponse> {
  return request<ArchiveSlidesResponse>(`${BASE}/archive`, {
    method: 'POST',
    body: JSON.stringify({ ids })
  });
}

async function exportPdf(ids: number[], filename?: string): Promise<PdfExportResponse> {
  const acceptedResponse = await fetchWithTimeout(`${API_BASE}${BASE}/export/pdf/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    credentials: 'include',
    body: JSON.stringify({ ids, filename: filename?.trim() || null })
  });
  const accepted = await parseResponse<SlideScannerTaskAcceptedResponse>(acceptedResponse);

  let completed = false;
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const status = await request<SlideScannerTaskStatusResponse<{ filename?: string }>>(`${BASE}/tasks/${accepted.task_id}`);
    if (status.status === 'failed') throw new Error(status.error_message || 'PDF 내보내기 실패');
    if (status.status === 'completed') {
      completed = true;
      break;
    }
    await wait(1000);
  }
  if (!completed) throw new Error('PDF 내보내기 상태 확인 시간이 초과되었습니다.');

  const response = await fetchWithTimeout(`${API_BASE}${BASE}/export/pdf/tasks/${accepted.task_id}/result`, {
    headers: authHeaders(),
    credentials: 'include'
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body?.detail ?? message;
    } catch {
      // ignore JSON parsing errors
    }
    throw new Error(message || 'PDF 내보내기 실패');
  }

  const blob = await response.blob();
  const headerFilename = parseContentDispositionFilename(response.headers.get('content-disposition'));
  const fallbackName = filename?.trim() ? `${filename.trim().replace(/\.pdf$/i, '')}.pdf` : 'slides_export.pdf';
  return {
    blob,
    filename: headerFilename || fallbackName
  };
}

function getSettings(): Promise<SlideScannerSettings> {
  return request<SlideScannerSettings>(`${BASE}/settings`);
}

function updateSettings(payload: {
  scan_path?: string;
  output_path?: string;
}): Promise<SlideScannerSettings> {
  return request<SlideScannerSettings>(`${BASE}/settings`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

function getHealth(): Promise<{
  status: string;
  module: string;
  database: { ok: boolean; error: string | null };
}> {
  return request(`${BASE}/health`);
}

function getMobileDevices(): Promise<MobileSyncDevicesResponse> {
  return request<MobileSyncDevicesResponse>(`${BASE}/mobile-sync/devices`);
}

function runMobileSync(payload: { background?: boolean } = {}): Promise<MobileSyncRunResponse> {
  return request<MobileSyncRunResponse>(`${BASE}/mobile-sync/run`, {
    method: 'POST',
    body: JSON.stringify({
      background: payload.background ?? true
    })
  });
}

function getMobileSyncStatus(): Promise<MobileSyncStatusResponse> {
  return request<MobileSyncStatusResponse>(`${BASE}/mobile-sync/status`);
}

function getMobileReviewItems(params: {
  deviceId?: string;
  approvalStatus?: MobileApprovalStatus | MobileApprovalStatus[];
  skip?: number;
  limit?: number;
} = {}): Promise<MobileReviewItemsResponse> {
  const search = new URLSearchParams();
  if (params.deviceId) search.set('device_id', params.deviceId);
  if (params.approvalStatus) {
    const statuses = Array.isArray(params.approvalStatus) ? params.approvalStatus : [params.approvalStatus];
    for (const status of statuses) {
      search.append('approval_status', status);
    }
  }
  if (params.skip !== undefined) search.set('skip', String(params.skip));
  if (params.limit !== undefined) search.set('limit', String(params.limit));
  const query = search.toString();
  return request<MobileReviewItemsResponse>(`${BASE}/mobile-review/items${query ? `?${query}` : ''}`);
}

function approveMobileItem(itemId: number): Promise<MobileReviewUpdateResponse> {
  return request<MobileReviewUpdateResponse>(`${BASE}/mobile-review/${itemId}/approve`, {
    method: 'POST'
  });
}

function rejectMobileItem(itemId: number, reason: string): Promise<MobileReviewUpdateResponse> {
  return request<MobileReviewUpdateResponse>(`${BASE}/mobile-review/${itemId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason })
  });
}

function remoteDeleteMobileItem(itemId: number, retry = false): Promise<MobileRemoteDeleteResponse> {
  const suffix = retry ? '/remote-delete/retry/tasks' : '/remote-delete/tasks';
  return runTask<MobileRemoteDeleteResponse>(`${BASE}/mobile-review/${itemId}${suffix}`);
}

function handoffMobileItem(itemId: number): Promise<MobileHandoffResponse> {
  return request<MobileHandoffResponse>(`${BASE}/mobile-review/${itemId}/handoff`, {
    method: 'POST'
  });
}

function getMobileReviewImageUrl(itemId: number): string {
  return `${API_BASE}${BASE}/mobile-review/${itemId}/image`;
}

export const slideScannerApi = {
  uploadSlide,
  getSlide,
  getSlideWithInherited,
  getSlideList,
  getTags,
  transformSlide,
  reviewSlide,
  ocrSlide,
  updateSlide,
  scanFolder,
  batchTransform,
  archiveSlides,
  exportPdf,
  getSettings,
  updateSettings,
  getSlideImageUrl,
  getSlideThumbnailUrl,
  getSlideResultUrl,
  getHealth,
  getMobileDevices,
  runMobileSync,
  getMobileSyncStatus,
  getMobileReviewItems,
  approveMobileItem,
  rejectMobileItem,
  remoteDeleteMobileItem,
  handoffMobileItem,
  getMobileReviewImageUrl
};
