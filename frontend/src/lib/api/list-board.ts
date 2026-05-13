/**
 * List Board API — Markdown import / 아이템 조회
 */
import { request } from './client';

export interface ListBoardItem {
  id: number;
  title: string;
  url: string;
  duration_minutes: number | null;
  source: string | null;
  badge_type: string | null;
  properties: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ListBoardListResponse {
  items: ListBoardItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListBoardImportRequest {
  markdown_text: string;
  source: string;
  badge_type?: string;
}

export interface ListBoardImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export const listBoardApi = {
  async importItems(req: ListBoardImportRequest): Promise<ListBoardImportResult> {
    return request<ListBoardImportResult>('/list-board/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
  },

  async listItems(params?: {
    page?: number;
    page_size?: number;
    source?: string;
    badge_type?: string;
  }): Promise<ListBoardListResponse> {
    const q = new URLSearchParams();
    if (params?.page) q.set('page', String(params.page));
    if (params?.page_size) q.set('page_size', String(params.page_size));
    if (params?.source) q.set('source', params.source);
    if (params?.badge_type) q.set('badge_type', params.badge_type);
    const qs = q.toString();
    return request<ListBoardListResponse>(`/list-board/items${qs ? '?' + qs : ''}`);
  },
};
