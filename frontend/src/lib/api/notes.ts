/**
 * Notes API - 메모 CRUD
 */
import { getAuthToken, fetchWithTimeout } from './client';

// ============================================================
// Types
// ============================================================

export interface NoteTag {
  id: number;
  name: string;
  color: string;
}

export interface Note {
  id: number;
  title: string;
  content: string;
  remark: string | null;
  is_pinned: boolean;
  is_starred: boolean;
  tags: NoteTag[];
  created_at: string;
  updated_at: string;
}

export interface NoteCreate {
  title: string;
  content?: string;
  remark?: string;
  tag_ids?: number[];
}

export interface NoteUpdate {
  title?: string;
  content?: string;
  remark?: string;
  tag_ids?: number[];
}

export interface NoteListResponse {
  items: Note[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface NoteArchive {
  id: number;
  original_id: number;
  title: string;
  content: string;
  remark: string | null;
  tags: NoteTag[];
  created_at: string;
  updated_at: string;
  archived_at: string;
}

export interface ArchiveListResponse {
  items: NoteArchive[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface TagDef {
  id: number;
  name: string;
  color: string;
  note_count: number;
  created_at: string;
}

export interface TagCreate {
  name: string;
  color?: string;
}

export interface TagUpdate {
  name?: string;
  color?: string;
}

export interface NoteHistoryItem {
  id: number;
  title: string;
  content: string;
  remark: string | null;
  changed_at: string;
}

// ============================================================
// API Client
// ============================================================

const BASE = '/api/notes';

function headers(): Record<string, string> {
  const token = getAuthToken();
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetchWithTimeout(`${BASE}${path}`, {
    method,
    headers: headers(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const notesApi = {
  // ── Notes ──
  list(params?: {
    tag?: string;
    tags?: string;
    tag_mode?: string;
    search?: string;
    date_from?: string;
    date_to?: string;
    sort?: string;
    order?: string;
    page?: number;
    page_size?: number;
    starred?: boolean;
  }): Promise<NoteListResponse> {
    const q = new URLSearchParams();
    if (params?.tag) q.set('tags', params.tag);
    if (params?.tags) q.set('tags', params.tags);
    if (params?.tag_mode) q.set('tag_mode', params.tag_mode);
    if (params?.search) q.set('search', params.search);
    if (params?.date_from) q.set('date_from', params.date_from);
    if (params?.date_to) q.set('date_to', params.date_to);
    if (params?.sort) q.set('sort', params.sort);
    if (params?.order) q.set('order', params.order);
    if (params?.page) q.set('page', String(params.page));
    if (params?.page_size) q.set('page_size', String(params.page_size));
    if (params?.starred !== undefined) q.set('starred', String(params.starred));
    return req('GET', `?${q}`);
  },

  searchTitles(q: string, limit?: number): Promise<{ id: number; title: string }[]> {
    const params = new URLSearchParams({ q });
    if (limit) params.set('limit', String(limit));
    return req('GET', `/search/titles?${params}`);
  },

  get(id: number): Promise<Note> {
    return req('GET', `/${id}`);
  },

  create(data: NoteCreate): Promise<Note> {
    return req('POST', '', data);
  },

  update(id: number, data: NoteUpdate): Promise<Note> {
    return req('PUT', `/${id}`, data);
  },

  remove(id: number, hard = false): Promise<{ ok: boolean }> {
    return req('DELETE', `/${id}?hard=${hard}`);
  },

  togglePin(id: number): Promise<Note> {
    return req('POST', `/${id}/pin`);
  },

  toggleStar(id: number): Promise<Note> {
    return req('POST', `/${id}/star`);
  },

  // ── Archive ──
  archive(id: number): Promise<NoteArchive> {
    return req('POST', `/${id}/archive`);
  },

  listArchive(params?: { tag?: string; page?: number; page_size?: number }): Promise<ArchiveListResponse> {
    const q = new URLSearchParams();
    if (params?.tag) q.set('tag', params.tag);
    if (params?.page) q.set('page', String(params.page));
    if (params?.page_size) q.set('page_size', String(params.page_size));
    return req('GET', `/archive?${q}`);
  },

  getArchive(id: number): Promise<NoteArchive> {
    return req('GET', `/archive/${id}`);
  },

  restoreArchive(id: number): Promise<Note> {
    return req('POST', `/archive/${id}/restore`);
  },

  deleteArchive(id: number): Promise<{ ok: boolean }> {
    return req('DELETE', `/archive/${id}`);
  },

  // ── Tags ──
  listTags(): Promise<TagDef[]> {
    return req('GET', '/tags');
  },

  createTag(data: TagCreate): Promise<TagDef> {
    return req('POST', '/tags', data);
  },

  updateTag(id: number, data: TagUpdate): Promise<TagDef> {
    return req('PUT', `/tags/${id}`, data);
  },

  deleteTag(id: number): Promise<{ ok: boolean }> {
    return req('DELETE', `/tags/${id}`);
  },

  // ── History ──
  getHistory(noteId: number): Promise<NoteHistoryItem[]> {
    return req('GET', `/${noteId}/history`);
  },

  // ── Bulk ──
  bulkDelete(noteIds: number[]): Promise<{ ok: boolean; count: number }> {
    return req('POST', '/bulk/delete', { note_ids: noteIds });
  },

  bulkArchive(noteIds: number[]): Promise<{ ok: boolean; count: number }> {
    return req('POST', '/bulk/archive', { note_ids: noteIds });
  },

  bulkTag(noteIds: number[], addTagIds: number[], removeTagIds: number[]): Promise<{ ok: boolean; count: number }> {
    return req('POST', '/bulk/tag', { note_ids: noteIds, add_tag_ids: addTagIds, remove_tag_ids: removeTagIds });
  },

  bulkStar(noteIds: number[], starred: boolean): Promise<{ ok: boolean; count: number }> {
    return req('POST', '/bulk/star', { note_ids: noteIds, starred });
  },
};
