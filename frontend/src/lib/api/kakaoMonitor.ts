/**
 * 카카오톡 모니터링 API 클라이언트
 */

import { request } from './client';

const BASE = '/kakao-monitor';

// ========== Types ==========

export interface KakaoConfig {
  id: number;
  chat_name: string;
  polling_interval_sec: number;
  is_active: boolean;
  keyword_count: number;
}

export interface KakaoKeyword {
  id: number;
  config_id: number;
  keyword: string;
  action_type: 'collect' | 'alert_only';
  is_active: boolean;
}

export interface KakaoPost {
  id: number;
  config_id: number;
  keyword_id: number | null;
  matched_keyword: string | null;
  trigger_message: string | null;
  collected_content: string | null;
  collected_at: string | null;
  screenshot_path: string | null;
  status: 'success' | 'partial' | 'failed';
}

export interface PostListResponse {
  items: KakaoPost[];
  total: number;
  skip: number;
  limit: number;
}

export interface WorkerStatus {
  is_kakao_running: boolean;
  main_window_found: boolean;
  active_config_count: number;
}

export interface WindowInfo {
  hwnd: number;
  title: string;
  hwnd_hex: string;
}

// ========== Config API ==========

export async function getConfigs(): Promise<KakaoConfig[]> {
  return request<KakaoConfig[]>(`${BASE}/configs`);
}

export async function createConfig(data: {
  chat_name: string;
  polling_interval_sec?: number;
  keywords?: string[];
}): Promise<KakaoConfig> {
  return request<KakaoConfig>(`${BASE}/configs`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateConfig(id: number, data: {
  chat_name?: string;
  polling_interval_sec?: number;
}): Promise<KakaoConfig> {
  return request<KakaoConfig>(`${BASE}/configs/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteConfig(id: number): Promise<void> {
  await request<void>(`${BASE}/configs/${id}`, { method: 'DELETE' });
}

export async function toggleConfig(id: number): Promise<KakaoConfig> {
  return request<KakaoConfig>(`${BASE}/configs/${id}/toggle`, { method: 'PATCH' });
}

// ========== Keyword API ==========

export async function getKeywords(configId: number): Promise<KakaoKeyword[]> {
  return request<KakaoKeyword[]>(`${BASE}/configs/${configId}/keywords`);
}

export async function addKeyword(configId: number, data: {
  keyword: string;
  action_type?: string;
}): Promise<KakaoKeyword> {
  return request<KakaoKeyword>(`${BASE}/configs/${configId}/keywords`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deleteKeyword(keywordId: number): Promise<void> {
  await request<void>(`${BASE}/keywords/${keywordId}`, { method: 'DELETE' });
}

// ========== History API ==========

export async function getPosts(params: {
  config_id?: number;
  skip?: number;
  limit?: number;
}): Promise<PostListResponse> {
  const qs = new URLSearchParams();
  if (params.config_id != null) qs.set('config_id', String(params.config_id));
  if (params.skip != null) qs.set('skip', String(params.skip));
  if (params.limit != null) qs.set('limit', String(params.limit));
  return request<PostListResponse>(`${BASE}/posts?${qs}`);
}

export async function getPost(id: number): Promise<KakaoPost> {
  return request<KakaoPost>(`${BASE}/posts/${id}`);
}

export async function deletePost(id: number): Promise<void> {
  await request<void>(`${BASE}/posts/${id}`, { method: 'DELETE' });
}

// ========== Worker & Window API ==========

export async function getStatus(): Promise<WorkerStatus> {
  return request<WorkerStatus>(`${BASE}/status`);
}

export async function triggerScan(): Promise<{ queued: boolean; message: string }> {
  return request<{ queued: boolean; message: string }>(`${BASE}/scan`, { method: 'POST' });
}

export async function getWindows(): Promise<WindowInfo[]> {
  return request<WindowInfo[]>(`${BASE}/windows`);
}
