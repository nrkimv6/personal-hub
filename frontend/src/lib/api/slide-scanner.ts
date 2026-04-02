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

export const slideScannerApi = {
  uploadSlide,
  getSlide,
  transformSlide,
  getSlideImageUrl,
  getSlideResultUrl,
  getHealth
};
