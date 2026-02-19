/**
 * Git Repository Manager API 클라이언트
 */
import { request } from './client';
import type {
  GitRepo,
  GitRepoCreate,
  GitRepoUpdate,
  GitStatus,
  GitLogEntry,
  OperationLog,
  OperationResult,
  BatchResult,
  DiscoverResult,
} from '../types/gitRepos';

const BASE = '/git-repos';

export const gitReposApi = {
  // ─────────────────────────────────────────────
  // CRUD
  // ─────────────────────────────────────────────

  /** 전체 레포지토리 목록 조회 */
  listRepos(): Promise<GitRepo[]> {
    return request<GitRepo[]>(BASE);
  },

  /** 레포지토리 등록 */
  createRepo(data: GitRepoCreate): Promise<GitRepo> {
    return request<GitRepo>(BASE, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /** 레포지토리 정보 수정 */
  updateRepo(id: number, data: GitRepoUpdate): Promise<GitRepo> {
    return request<GitRepo>(`${BASE}/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /** 레포지토리 등록 해제 */
  deleteRepo(id: number): Promise<{ success: boolean }> {
    return request<{ success: boolean }>(`${BASE}/${id}`, { method: 'DELETE' });
  },

  /** 디렉토리 탐색 */
  discoverRepos(basePath: string): Promise<DiscoverResult> {
    return request<DiscoverResult>(`${BASE}/discover?base_path=${encodeURIComponent(basePath)}`);
  },

  // ─────────────────────────────────────────────
  // 상태 조회
  // ─────────────────────────────────────────────

  /** 상세 상태 조회 */
  getStatus(id: number): Promise<GitStatus> {
    return request<GitStatus>(`${BASE}/${id}/status`);
  },

  /** diff 조회 */
  getDiff(id: number, staged = false): Promise<{ diff: string }> {
    return request<{ diff: string }>(`${BASE}/${id}/diff?staged=${staged}`);
  },

  /** 커밋 로그 조회 */
  getLog(id: number, n = 20): Promise<GitLogEntry[]> {
    return request<GitLogEntry[]>(`${BASE}/${id}/log?n=${n}`);
  },

  /** 단일 상태 갱신 */
  refreshRepo(id: number): Promise<GitRepo> {
    return request<GitRepo>(`${BASE}/${id}/refresh`, { method: 'POST' });
  },

  /** 전체 상태 갱신 */
  refreshAll(): Promise<GitRepo[]> {
    return request<GitRepo[]>(`${BASE}/refresh-all`, { method: 'POST' });
  },

  // ─────────────────────────────────────────────
  // 작업 실행
  // ─────────────────────────────────────────────

  /** 파일 스테이징 */
  stageFiles(id: number, files: string[]): Promise<OperationResult> {
    return request<OperationResult>(`${BASE}/${id}/stage`, {
      method: 'POST',
      body: JSON.stringify({ files }),
    });
  },

  /** 커밋 */
  commit(id: number, message: string, stageAll = false): Promise<OperationResult> {
    return request<OperationResult>(`${BASE}/${id}/commit`, {
      method: 'POST',
      body: JSON.stringify({ message, stage_all: stageAll }),
    });
  },

  /** 푸시 */
  push(id: number): Promise<OperationResult> {
    return request<OperationResult>(`${BASE}/${id}/push`, { method: 'POST' });
  },

  /** 풀 */
  pull(id: number): Promise<OperationResult> {
    return request<OperationResult>(`${BASE}/${id}/pull`, { method: 'POST' });
  },

  /** 페치 */
  fetch(id: number): Promise<OperationResult> {
    return request<OperationResult>(`${BASE}/${id}/fetch`, { method: 'POST' });
  },

  /** 스태시 저장 */
  stash(id: number, message?: string): Promise<OperationResult> {
    return request<OperationResult>(`${BASE}/${id}/stash`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
  },

  /** 스태시 복원 */
  stashPop(id: number): Promise<OperationResult> {
    return request<OperationResult>(`${BASE}/${id}/stash-pop`, { method: 'POST' });
  },

  // ─────────────────────────────────────────────
  // 일괄 작업 + LLM
  // ─────────────────────────────────────────────

  /** 일괄 커밋 */
  batchCommit(repoIds: number[], message: string): Promise<{ results: BatchResult[] }> {
    return request<{ results: BatchResult[] }>(`${BASE}/batch-commit`, {
      method: 'POST',
      body: JSON.stringify({ repo_ids: repoIds, message }),
    });
  },

  /** 일괄 푸시 */
  batchPush(repoIds: number[]): Promise<{ results: BatchResult[] }> {
    return request<{ results: BatchResult[] }>(`${BASE}/batch-push`, {
      method: 'POST',
      body: JSON.stringify({ repo_ids: repoIds }),
    });
  },

  /** LLM 커밋 메시지 자동 생성 */
  generateMessage(id: number): Promise<{ message: string; request_id: number; status?: string }> {
    return request(`${BASE}/${id}/generate-message`, { method: 'POST' });
  },

  /** 작업 이력 조회 */
  getOperations(id: number, limit = 50): Promise<OperationLog[]> {
    return request<OperationLog[]>(`${BASE}/${id}/operations?limit=${limit}`);
  },
};
