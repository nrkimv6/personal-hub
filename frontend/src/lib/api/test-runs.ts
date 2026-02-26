/**
 * Test Runs API — pytest 자동 실행 이력 조회 및 수동 트리거
 */

import { request } from './client';

export interface TestResultItem {
  id: number;
  test_name: string;
  status: 'passed' | 'failed' | 'error' | 'skipped';
  duration_seconds: number | null;
  error_message: string | null;
  traceback: string | null;
  fix_plan: string | null;
  llm_request_id: number | null;
}

export interface TestRunItem {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'completed' | 'failed';
  triggered_by: 'scheduler' | 'manual' | 'api';
  test_path: string;
  total_tests: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  duration_seconds: number | null;
  log_file_path: string | null;
  results: TestResultItem[];
}

export interface TriggerRunResponse {
  test_run_id: number;
  status: string;
  message: string;
}

export interface TestRunListParams {
  status?: string;
  limit?: number;
  offset?: number;
}

export const testRunsApi = {
  list(params: TestRunListParams = {}): Promise<TestRunItem[]> {
    const qs = new URLSearchParams();
    if (params.status) qs.set('status', params.status);
    if (params.limit !== undefined) qs.set('limit', String(params.limit));
    if (params.offset !== undefined) qs.set('offset', String(params.offset));
    const q = qs.toString();
    return request<TestRunItem[]>(`/test-runs${q ? '?' + q : ''}`);
  },

  get(id: number): Promise<TestRunItem> {
    return request<TestRunItem>(`/test-runs/${id}`);
  },

  getResults(id: number, status?: string): Promise<TestResultItem[]> {
    const q = status ? `?status=${status}` : '';
    return request<TestResultItem[]>(`/test-runs/${id}/results${q}`);
  },

  getLog(id: number): Promise<{ content: string; log_file_path: string }> {
    return request(`/test-runs/${id}/log`);
  },

  trigger(testPath = 'tests/', extraArgs: string[] = [], autoFixPlan = true, provider = 'claude', model = ''): Promise<TriggerRunResponse> {
    return request<TriggerRunResponse>('/test-runs', {
      method: 'POST',
      body: JSON.stringify({ test_path: testPath, extra_args: extraArgs, auto_fix_plan: autoFixPlan, provider, model })
    });
  }
};
