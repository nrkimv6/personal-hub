/**
 * Claude Sessions API 클라이언트
 */

import { request } from './client';

export interface SessionMeta {
  id: string;
  mtime: string;
  line_count: number;
  source_type: 'user' | 'agent' | 'llm-worker' | 'unknown';
  agent_name: string | null;
  cwd: string | null;
  git_branch: string | null;
  first_message: string | null;
  db_request_ids: number[];
  db_source_type: string | null;
}

export interface SummaryResult {
  session_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'not_found';
  summary: string | null;
}

export interface SessionFilter {
  limit?: number;
  since?: string;
  source_type?: 'user' | 'agent' | 'llm-worker';
}

export interface SummarizeResponse {
  request_id: number;
  status: string;
}

export interface SummarizeRecentResponse {
  request_ids: number[];
  count: number;
}

export interface ProjectInfo {
  encoded: string;
  decoded: string | null;
}

// API_BASE는 '/api/v1'이므로 endpoint는 '/api/v1' 이후 경로
const BASE = '/claude-sessions';

export const claudeSessionsApi = {
  listProjects(): Promise<ProjectInfo[]> {
    return request<ProjectInfo[]>(`${BASE}/projects`);
  },

  listSessions(encoded: string, filter: SessionFilter = {}): Promise<SessionMeta[]> {
    const params = new URLSearchParams();
    if (filter.limit) params.set('limit', String(filter.limit));
    if (filter.since) params.set('since', filter.since);
    if (filter.source_type) params.set('source_type', filter.source_type);
    const qs = params.toString();
    return request<SessionMeta[]>(`${BASE}/${encoded}/sessions${qs ? `?${qs}` : ''}`);
  },

  summarizeSession(encoded: string, sessionId: string): Promise<SummarizeResponse> {
    return request<SummarizeResponse>(`${BASE}/${encoded}/sessions/${sessionId}/summarize`, {
      method: 'POST',
    });
  },

  getSummary(sessionId: string): Promise<SummaryResult> {
    return request<SummaryResult>(`${BASE}/summary/${sessionId}`);
  },

  summarizeRecent(encoded: string, filter: SessionFilter = {}): Promise<SummarizeRecentResponse> {
    const params = new URLSearchParams();
    if (filter.limit) params.set('limit', String(filter.limit));
    if (filter.since) params.set('since', filter.since);
    if (filter.source_type) params.set('source_type', filter.source_type);
    const qs = params.toString();
    return request<SummarizeRecentResponse>(`${BASE}/${encoded}/summarize-recent${qs ? `?${qs}` : ''}`, {
      method: 'POST',
    });
  },
};
