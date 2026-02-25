/**
 * Git Repository Manager TypeScript 타입 정의
 */

export interface GitRepo {
  id: number;
  path: string;
  alias: string | null;
  is_active: boolean;
  sort_order: number;
  last_status: 'clean' | 'dirty' | 'conflict' | 'unknown' | null;
  last_branch: string | null;
  last_ahead: number | null;
  last_behind: number | null;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface GitRepoCreate {
  path: string;
  alias?: string;
}

export interface GitRepoUpdate {
  alias?: string;
  is_active?: boolean;
  sort_order?: number;
}

export interface GitStatus {
  branch: string;
  upstream: string | null;
  ahead: number;
  behind: number;
  status: 'clean' | 'dirty' | 'conflict' | 'unknown';
  staged: string[];
  unstaged: string[];
  untracked: string[];
}

export interface GitLogEntry {
  hash: string;
  short_hash: string;
  message: string;
  author: string;
  date: string;
}

export interface OperationLog {
  id: number;
  repo_id: number;
  operation: string;
  status: 'success' | 'failure';
  message: string | null;
  detail: string | null;
  created_at: string;
}

export interface OperationResult {
  success: boolean;
  stdout: string | null;
  stderr: string | null;
  message: string | null;
}

export interface BatchResult {
  repo_id: number;
  success: boolean;
  message: string | null;
}

export interface DiscoverResult {
  paths: string[];
  count: number;
}

export interface GitTaskResponse {
  task_id: string;
  status: 'pending' | 'completed' | 'failed';
  results?: BatchResult[];
}

export interface GitTaskResult {
  task_id: string;
  status: string;
  result?: OperationResult;
  completed_at?: string;
}
