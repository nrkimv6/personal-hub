import type {
  ExpoCollectionStatusResponse,
  ExpoExportPayload,
  ExpoExportRecordResponse,
  ExpoMapMeta,
  ExpoPipelineStatusResponse,
  ExpoPublishedStatusResponse,
} from '$lib/types';

import { API_BASE, getAuthToken, request } from './client';

const BASE = '/expo';

export const expoApi = {
  getPipelineStatus(slug: string) {
    return request<ExpoPipelineStatusResponse>(`${BASE}/${slug}/pipeline-status`);
  },

  getCollectionStatus(slug: string) {
    return request<ExpoCollectionStatusResponse>(`${BASE}/${slug}/collection-status`);
  },

  getPublishedStatus(slug: string) {
    return request<ExpoPublishedStatusResponse>(`${BASE}/${slug}/published-status`);
  },

  recordExport(slug: string, payload: ExpoExportPayload) {
    return request<ExpoExportRecordResponse>(`${BASE}/${slug}/exports/record`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** 배치도 업로드 override 메타데이터 조회 (public) */
  getMapMeta(slug: string) {
    return request<ExpoMapMeta>(`${BASE}/maps/${slug}`);
  },

  /** 배치도 이미지 업로드 (admin only). FormData를 사용하므로 fetch 직접 호출 */
  async uploadMap(slug: string, file: File): Promise<ExpoMapMeta> {
    const formData = new FormData();
    formData.append('file', file);

    const token = getAuthToken();
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

    const res = await fetch(`${API_BASE}${BASE}/maps/${slug}/upload`, {
      method: 'POST',
      body: formData,
      headers,
      credentials: 'include',
    });

    if (!res.ok) {
      let detail = `업로드 실패 (${res.status})`;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch {
        // ignore
      }
      throw new Error(detail);
    }

    return res.json() as Promise<ExpoMapMeta>;
  },

  /** 배치도 업로드 override 삭제 (admin only) */
  deleteMapOverride(slug: string) {
    return request<void>(`${BASE}/maps/${slug}`, { method: 'DELETE' });
  },
};
