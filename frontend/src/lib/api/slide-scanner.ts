import { API_BASE, fetchWithTimeout, getAuthToken, request } from './client';

const BASE = '/ss';

export interface SlidePoint {
  x: number;
  y: number;
}

export interface SlideUploadResponse {
  id: number;
  status: 'PENDING' | 'REVIEWED' | 'DONE';
  points: SlidePoint[];
  thumbnail_base64?: string | null;
}

export interface SlideDetailResponse {
  id: number;
  file_name: string;
  status: 'PENDING' | 'REVIEWED' | 'DONE';
  captured_at?: string | null;
  source_app?: string | null;
  points: SlidePoint[];
  has_result: boolean;
  thumbnail_base64?: string | null;
}

export interface SlideTransformResponse {
  id: number;
  status: 'DONE';
  result_path: string;
  result_url: string;
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

export interface MobileReviewItem {
  id: number;
  device_id: string;
  device_serial: string;
  device_alias?: string | null;
  original_filename: string;
  source_uri: string;
  pc_inbox_path: string;
  captured_at_utc: string;
  approval_status: 'PENDING' | 'APPROVED' | 'REJECTED';
  remote_delete_status: 'PENDING' | 'DONE' | 'FAILED';
  handoff_status: 'PENDING' | 'DONE' | 'FAILED';
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
  approval_status: 'APPROVED' | 'REJECTED';
  reason?: string;
}

export interface MobileRemoteDeleteResponse {
  status: 'done' | 'failed' | 'skipped_done';
  item_id: number;
  results: Record<string, boolean>;
  error?: string;
}

export interface MobileHandoffResponse {
  item_id: number;
  slide_id: number;
  slide_url: string;
}

function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body?.detail ?? message;
    } catch {
      // ignore JSON parsing errors
    }
    throw new Error(message || '요청 실패');
  }
  return response.json() as Promise<T>;
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

function transformSlide(
  slideId: number,
  points: SlidePoint[],
  aspectRatio?: string
): Promise<SlideTransformResponse> {
  return request<SlideTransformResponse>(`${BASE}/slides/${slideId}/transform`, {
    method: 'POST',
    body: JSON.stringify({
      points,
      aspect_ratio: aspectRatio ?? null
    })
  });
}

function getSlideImageUrl(slideId: number): string {
  return `${API_BASE}${BASE}/slides/${slideId}/image`;
}

function getSlideResultUrl(slideId: number): string {
  return `${API_BASE}${BASE}/slides/${slideId}/result`;
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
  skip?: number;
  limit?: number;
} = {}): Promise<MobileReviewItemsResponse> {
  const search = new URLSearchParams();
  if (params.deviceId) search.set('device_id', params.deviceId);
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
  const suffix = retry ? '/remote-delete/retry' : '/remote-delete';
  return request<MobileRemoteDeleteResponse>(`${BASE}/mobile-review/${itemId}${suffix}`, {
    method: 'POST'
  });
}

function handoffMobileItem(itemId: number): Promise<MobileHandoffResponse> {
  return request<MobileHandoffResponse>(`${BASE}/mobile-review/${itemId}/handoff`, {
    method: 'POST'
  });
}

function getMobileReviewImageUrl(itemId: number): string {
  return `${API_BASE}${BASE}/mobile-review/${itemId}/image`;
}

async function getMobileReviewImageFile(itemId: number, fileName: string): Promise<File> {
  const response = await fetchWithTimeout(getMobileReviewImageUrl(itemId), {
    method: 'GET',
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
    throw new Error(message || '이미지 로드 실패');
  }

  const blob = await response.blob();
  const mime = blob.type || 'image/jpeg';
  return new File([blob], fileName, { type: mime });
}

export const slideScannerApi = {
  uploadSlide,
  getSlide,
  transformSlide,
  getSlideImageUrl,
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
  getMobileReviewImageUrl,
  getMobileReviewImageFile
};
