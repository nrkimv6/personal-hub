import { API_BASE, fetchWithTimeout, getAuthToken, request } from './client';

export type Mp4GifTaskStatus = 'queued' | 'running' | 'completed' | 'failed';

export interface Mp4GifTaskAcceptedResponse {
  task_id: string;
  status: Mp4GifTaskStatus;
}

export interface Mp4GifTaskStatusResponse {
  task_id: string;
  status: Mp4GifTaskStatus;
  source_name: string;
  fps: number;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface Mp4GifHealthResponse {
  ffmpeg_ok: boolean;
  ffmpeg_path?: string | null;
  work_root: string;
  work_root_exists: boolean;
  max_upload_mb: number;
  error_message?: string | null;
}

function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = '요청 실패';
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string' && body.detail.trim()) {
        message = body.detail;
      }
    } catch {
      // ignore JSON parsing failures
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function createTask(formData: FormData): Promise<Mp4GifTaskAcceptedResponse> {
  const response = await fetchWithTimeout(`${API_BASE}/mp4-gif/tasks`, {
    method: 'POST',
    body: formData,
    headers: authHeaders(),
    credentials: 'include'
  });
  return parseResponse<Mp4GifTaskAcceptedResponse>(response);
}

export function getTask(taskId: string): Promise<Mp4GifTaskStatusResponse> {
  return request<Mp4GifTaskStatusResponse>(`/mp4-gif/tasks/${taskId}`);
}

export function getHealth(): Promise<Mp4GifHealthResponse> {
  return request<Mp4GifHealthResponse>('/mp4-gif/health');
}

export function getResultUrl(taskId: string): string {
  return `${API_BASE}/mp4-gif/tasks/${taskId}/result`;
}
