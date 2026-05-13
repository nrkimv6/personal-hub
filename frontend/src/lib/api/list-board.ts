/**
 * List Board API — Markdown import / 아이템 조회 / 컬럼 관리 / properties patch
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

export type ColumnType = 'checkbox' | 'text' | 'select' | 'priority';

export interface ListBoardColumn {
  id: number;
  key: string;
  display_name: string;
  column_type: ColumnType;
  options: string[];
  sort_order: number;
  is_visible: boolean;
  created_at: string;
}

export interface ColumnCreate {
  key: string;
  display_name: string;
  column_type: ColumnType;
  options?: string[];
  sort_order?: number;
}

export interface ColumnUpdate {
  display_name?: string;
  options?: string[];
  sort_order?: number;
  is_visible?: boolean;
}

export interface ListBoardSource {
  source: string | null;
  count: number;
  last_import_at: string | null;
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
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }): Promise<ListBoardListResponse> {
    const q = new URLSearchParams();
    if (params?.page) q.set('page', String(params.page));
    if (params?.page_size) q.set('page_size', String(params.page_size));
    if (params?.source) q.set('source', params.source);
    if (params?.badge_type) q.set('badge_type', params.badge_type);
    if (params?.sort_by) q.set('sort_by', params.sort_by);
    if (params?.sort_order) q.set('sort_order', params.sort_order);
    const qs = q.toString();
    return request<ListBoardListResponse>(`/list-board/items${qs ? '?' + qs : ''}`);
  },

  async patchItemProperties(itemId: number, properties: Record<string, unknown>): Promise<ListBoardItem> {
    return request<ListBoardItem>(`/list-board/items/${itemId}/properties`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ properties }),
    });
  },

  async listColumns(): Promise<ListBoardColumn[]> {
    return request<ListBoardColumn[]>('/list-board/columns');
  },

  async createColumn(req: ColumnCreate): Promise<ListBoardColumn> {
    return request<ListBoardColumn>('/list-board/columns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
  },

  async updateColumn(columnId: number, req: ColumnUpdate): Promise<ListBoardColumn> {
    return request<ListBoardColumn>(`/list-board/columns/${columnId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
  },

  async deleteColumn(columnId: number): Promise<void> {
    await request<void>(`/list-board/columns/${columnId}`, { method: 'DELETE' });
  },

  async listSources(): Promise<ListBoardSource[]> {
    return request<ListBoardSource[]>('/list-board/sources');
  },
};
