/**
 * Writing API - 글쓰기 워커 및 키워드 관리
 */
import { getAuthToken } from './client';

// ============================================================
// Types
// ============================================================

export interface GeneratedWriting {
  id: number;
  task_type: 'mix' | 'random';
  source_ids: number[];
  content: string;
  preview: string;
  raw_response?: string;
  prompt_used?: string;
  rating: number | null;  // 1: like, -1: dislike, null: unrated
  schedule_run_id?: number;
  created_at: string;
  updated_at?: string;
}

export interface WritingSource {
  id: number;
  content: string;
  preview: string;
  category?: string;
  source_info?: string;
  created_at: string;
}

export interface WritingStats {
  source_count: number;
  generated_count: number;
  by_type: { mix: number; random: number };
  by_rating: { liked: number; disliked: number };
  today_count: number;
}

export interface GeneratedWritingListResponse {
  items: GeneratedWriting[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface WritingSourceListResponse {
  items: WritingSource[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface WritingElement {
  id: number;
  category: string;
  name: string;
  source_type: string;  // 'seed', 'auto', 'manual'
  frequency: number;
  is_active: boolean;
  created_at: string | null;
}

export interface WritingElementListResponse {
  items: WritingElement[];
  total: number;
  page: number;
  pages: number;
}

export interface WritingElementStats {
  by_category: Record<string, number>;
  by_source_type: Record<string, number>;
  topic_by_source: Record<string, number>;
  total: number;
}

export interface KeywordStats {
  id: number;
  keyword: string;
  frequency: number;
  source_count: number;
  avg_per_source: number;
  is_stopword: boolean;
  is_promoted: boolean;
  element_id: number | null;
  reviewed_at: string | null;
  analyzed_at: string | null;
}

export interface KeywordStatsResponse {
  total_keywords: number;
  promoted: number;
  stopwords: number;
  reviewed: number;
  pending_review: number;
}

export interface Stopword {
  id: number;
  word: string;
  category: string;
  created_at: string | null;
}

// ============================================================
// Helper: Writing API Request Function
// ============================================================

async function requestWriting<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `/api/writing${endpoint}`;

  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers
  };

  const response = await fetch(url, { ...options, headers, credentials: 'include' });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || '요청 실패');
  }

  if (response.status === 204) {
    return null as T;
  }

  return response.json();
}

// Helper function for keyword API
async function requestKeyword<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `/api/writing/keywords${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `API 요청 실패: ${response.status}`);
  }

  return response.json();
}

// ============================================================
// Writing API
// ============================================================

export const writingApi = {
  // 생성된 글 목록 조회
  listGenerated: (params?: {
    task_type?: string;
    rating?: string;  // '1', '-1', 'null'
    page?: number;
    page_size?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.task_type) searchParams.set('task_type', params.task_type);
    if (params?.rating) searchParams.set('rating', params.rating);
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.page_size) searchParams.set('page_size', params.page_size.toString());
    const query = searchParams.toString();
    return requestWriting<GeneratedWritingListResponse>(`/generated${query ? `?${query}` : ''}`);
  },

  // 생성된 글 상세 조회
  getGenerated: (id: number) =>
    requestWriting<GeneratedWriting>(`/generated/${id}`),

  // 생성된 글 수정
  updateGenerated: (id: number, data: { content?: string }) =>
    requestWriting<GeneratedWriting>(`/generated/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // 생성된 글 삭제
  deleteGenerated: (id: number, hard = false) => {
    const query = hard ? '?hard=true' : '';
    return requestWriting<{ deleted: boolean }>(`/generated/${id}${query}`, {
      method: 'DELETE'
    });
  },

  // 생성된 글 평가
  rateGenerated: (id: number, rating: number | null) =>
    requestWriting<{ id: number; rating: number | null }>(`/generated/${id}/rate`, {
      method: 'POST',
      body: JSON.stringify({ rating })
    }),

  // 소스 목록 조회
  listSources: (params?: {
    category?: string;
    page?: number;
    page_size?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.category) searchParams.set('category', params.category);
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.page_size) searchParams.set('page_size', params.page_size.toString());
    const query = searchParams.toString();
    return requestWriting<WritingSourceListResponse>(`/sources${query ? `?${query}` : ''}`);
  },

  // 소스 상세 조회
  getSource: (id: number) =>
    requestWriting<WritingSource>(`/sources/${id}`),

  // 소스 추가
  addSource: (data: { content: string; category?: string; source_info?: string }) =>
    requestWriting<WritingSource>('/sources', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 소스 일괄 추가
  bulkAddSources: (sources: { content: string; category?: string; source_info?: string }[]) =>
    requestWriting<{ added: number }>('/sources/bulk', {
      method: 'POST',
      body: JSON.stringify({ sources })
    }),

  // 소스 삭제
  deleteSource: (id: number) =>
    requestWriting<{ deleted: boolean }>(`/sources/${id}`, {
      method: 'DELETE'
    }),

  // 통계 조회
  getStats: () => requestWriting<WritingStats>('/stats'),

  // 수동 실행
  run: () =>
    requestWriting<{ run_id: number; schedule_id: number; success: boolean; mix_count: number; random_count: number }>('/run', {
      method: 'POST'
    }),

  // 소재(elements) 목록 조회
  listElements: (params?: {
    category?: string;
    source_type?: string;
    page?: number;
    page_size?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.category) searchParams.set('category', params.category);
    if (params?.source_type) searchParams.set('source_type', params.source_type);
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.page_size) searchParams.set('page_size', params.page_size.toString());
    const query = searchParams.toString();
    return requestWriting<WritingElementListResponse>(`/elements${query ? `?${query}` : ''}`);
  },

  // 소재 통계 조회
  getElementsStats: () => requestWriting<WritingElementStats>('/elements/stats'),

  // 소재 삭제 (비활성화)
  deleteElement: (id: number) =>
    requestWriting<{ success: boolean }>(`/elements/${id}`, {
      method: 'DELETE'
    }),

  // 소재 추출 요청 생성
  extractTopics: (limit: number = 100) =>
    requestWriting<{ success: boolean; created_requests: number }>(`/extract-topics?limit=${limit}`, {
      method: 'POST'
    })
};

// ============================================================
// Keyword API
// ============================================================

export const keywordApi = {
  // 키워드 목록 조회
  list: (params?: {
    limit?: number;
    offset?: number;
    min_frequency?: number;
    include_stopwords?: boolean;
    include_promoted?: boolean;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.offset) searchParams.set('offset', params.offset.toString());
    if (params?.min_frequency) searchParams.set('min_frequency', params.min_frequency.toString());
    if (params?.include_stopwords !== undefined) searchParams.set('include_stopwords', params.include_stopwords.toString());
    if (params?.include_promoted !== undefined) searchParams.set('include_promoted', params.include_promoted.toString());
    const query = searchParams.toString();
    return requestKeyword<{ items: KeywordStats[]; count: number; total: number; offset: number; limit: number }>(`${query ? `?${query}` : ''}`);
  },

  // 승격 후보 조회
  candidates: (params?: { limit?: number; min_frequency?: number }) => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.min_frequency) searchParams.set('min_frequency', params.min_frequency.toString());
    const query = searchParams.toString();
    return requestKeyword<{ items: KeywordStats[]; count: number }>(`/candidates${query ? `?${query}` : ''}`);
  },

  // 통계 조회
  stats: () => requestKeyword<KeywordStatsResponse>('/stats'),

  // 키워드 승격
  promote: (keyword_id: number, season_hint?: string) =>
    requestKeyword<{ success: boolean; element: { id: number; name: string; category: string; frequency: number } }>('/promote', {
      method: 'POST',
      body: JSON.stringify({ keyword_id, season_hint })
    }),

  // 일괄 승격
  promoteBatch: (params: { limit?: number; min_frequency?: number; season_hint?: string }) =>
    requestKeyword<{ success: boolean; promoted_count: number; elements: { id: number; name: string; frequency: number }[] }>('/promote-batch', {
      method: 'POST',
      body: JSON.stringify(params)
    }),

  // 불용어 마킹
  markStopword: (keyword_id: number) =>
    requestKeyword<{ success: boolean; keyword: string }>(`/${keyword_id}/mark-stopword`, {
      method: 'POST'
    }),

  // 승격된 키워드 삭제
  demote: (keyword_id: number) =>
    requestKeyword<{ success: boolean; keyword: string }>(`/${keyword_id}`, {
      method: 'DELETE'
    }),

  // 분석 실행
  analyze: (params: { mode?: 'full' | 'incremental'; min_freq?: number; min_length?: number }) =>
    requestKeyword<{ success: boolean; mode: string; total_sources?: number; total_keywords?: number; saved_keywords?: number; new_sources?: number; new_keywords?: number; updated_keywords?: number }>('/analyze', {
      method: 'POST',
      body: JSON.stringify(params)
    }),

  // 불용어 목록 조회
  listStopwords: () =>
    requestKeyword<{ items: Stopword[]; count: number }>('/stopwords'),

  // 불용어 추가
  addStopword: (word: string, category?: string) =>
    requestKeyword<{ success: boolean; stopword: { id: number; word: string; category: string } }>('/stopwords', {
      method: 'POST',
      body: JSON.stringify({ word, category: category || 'general' })
    }),

  // 불용어 삭제
  removeStopword: (id: number) =>
    requestKeyword<{ deleted: boolean }>(`/stopwords/${id}`, {
      method: 'DELETE'
    })
};
