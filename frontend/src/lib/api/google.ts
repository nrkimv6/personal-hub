/**
 * Google 검색결과 관리 API
 */
import { request } from './client';
import type {
  SearchResultListItem,
  SearchResultDetail,
  SearchResultsListResponse,
  DisappearedResultsResponse,
  ResultStatsResponse,
  SearchResultListParams
} from '../types';

// ============================================================
// 검색결과 관리 API
// ============================================================

export const searchResultApi = {
  /**
   * 통합 검색결과 목록 조회
   */
  list: (params?: SearchResultListParams) => {
    const queryParams = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          queryParams.append(key, String(value));
        }
      });
    }
    const queryString = queryParams.toString();
    const url = queryString ? `/google/results/all?${queryString}` : '/google/results/all';
    return request<SearchResultsListResponse>(url);
  },

  /**
   * 검색결과 상세 조회
   */
  get: (id: number) => request<SearchResultDetail>(`/google/results/${id}`),

  /**
   * 읽음 상태 토글
   */
  toggleRead: (id: number) =>
    request<{ is_read: boolean }>(`/google/results/${id}/toggle-read`, {
      method: 'POST'
    }),

  /**
   * 북마크 상태 토글
   */
  toggleBookmark: (id: number) =>
    request<{ is_bookmarked: boolean }>(`/google/results/${id}/toggle-bookmark`, {
      method: 'POST'
    }),

  /**
   * 메모 수정
   */
  updateMemo: (id: number, memo: string | null) =>
    request<{ memo: string | null }>(`/google/results/${id}/memo`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ memo })
    }),

  /**
   * 사라진 결과 목록 조회
   */
  disappeared: (params?: { saved_search_id?: number; query?: string; page?: number; page_size?: number }) => {
    const queryParams = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          queryParams.append(key, String(value));
        }
      });
    }
    const queryString = queryParams.toString();
    const url = queryString ? `/google/results/disappeared?${queryString}` : '/google/results/disappeared';
    return request<DisappearedResultsResponse>(url);
  },

  /**
   * 검색결과 통계 조회
   */
  stats: () => request<ResultStatsResponse>('/google/results/stats')
};
