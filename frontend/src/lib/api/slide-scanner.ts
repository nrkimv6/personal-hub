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
  captured_at?: string | null;
  source_app?: string | null;
  aspect_ratio?: Exclude<AspectRatioValue, 'AUTO'> | null;
  filters_applied?: SlideFilterOptions | null;
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
  aspect_ratio?: Exclude<AspectRatioValue, 'AUTO'> | null;
  filters_applied?: SlideFilterOptions | null;
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

export interface SlideScannerSettings {
  scan_path?: string | null;
  output_path: string;
  archive_path: string;
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
  return request<SlideTransformResponse>(`${BASE}/slides/${slideId}/transform`, {
    method: 'POST',
    body: JSON.stringify({
      points,
      aspect_ratio: aspectRatio && aspectRatio !== 'AUTO' ? aspectRatio : null,
      filters: normalizeFilterPayload(filters)
    })
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
}): Promise<SlideListResponse> {
  const query = new URLSearchParams();
  if (typeof params?.skip === 'number') query.set('skip', String(params.skip));
  if (typeof params?.limit === 'number') query.set('limit', String(params.limit));
  if (params?.status && params.status !== 'ALL') query.set('status', params.status);

  const qs = query.toString();
  const path = qs ? `${BASE}/slides?${qs}` : `${BASE}/slides`;
  return request<SlideListResponse>(path);
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
  return request<BatchTransformResponse>(`${BASE}/slides/batch-transform`, {
    method: 'POST',
    body: JSON.stringify({
      ids,
      aspect_ratio:
        options?.aspectRatio && options.aspectRatio !== 'AUTO' ? options.aspectRatio : null,
      filters: normalizeFilterPayload(options?.filters)
    })
  });
}

function archiveSlides(ids: number[]): Promise<ArchiveSlidesResponse> {
  return request<ArchiveSlidesResponse>(`${BASE}/archive`, {
    method: 'POST',
    body: JSON.stringify({ ids })
  });
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

export const slideScannerApi = {
  uploadSlide,
  getSlide,
  getSlideWithInherited,
  getSlideList,
  transformSlide,
  reviewSlide,
  scanFolder,
  batchTransform,
  archiveSlides,
  getSettings,
  updateSettings,
  getSlideImageUrl,
  getSlideThumbnailUrl,
  getSlideResultUrl,
  getHealth
};
