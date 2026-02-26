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
  GitTaskResponse,
  GitTaskResult,
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

  /** 단일 상태 갱신 (큐 발행) */
  refreshRepo(id: number): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/refresh`, { method: 'POST' });
  },

  /** 전체 상태 갱신 (큐 발행) */
  refreshAll(): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/refresh-all`, { method: 'POST' });
  },

  // ─────────────────────────────────────────────
  // 작업 실행 (큐 발행)
  // ─────────────────────────────────────────────

  /** 파일 스테이징 */
  stageFiles(id: number, files: string[]): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/stage`, {
      method: 'POST',
      body: JSON.stringify({ files }),
    });
  },

  /** 파일 언스테이징 */
  unstageFiles(id: number, files: string[]): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/unstage`, {
      method: 'POST',
      body: JSON.stringify({ files }),
    });
  },

  /** 커밋 */
  commit(id: number, message: string, stageAll = false): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/commit`, {
      method: 'POST',
      body: JSON.stringify({ message, stage_all: stageAll }),
    });
  },

  /** 푸시 */
  push(id: number): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/push`, { method: 'POST' });
  },

  /** 풀 */
  pull(id: number): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/pull`, { method: 'POST' });
  },

  /** 페치 */
  fetch(id: number): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/fetch`, { method: 'POST' });
  },

  /** 스태시 저장 */
  stash(id: number, message?: string): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/stash`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
  },

  /** 스태시 복원 */
  stashPop(id: number): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/${id}/stash-pop`, { method: 'POST' });
  },

  // ─────────────────────────────────────────────
  // 일괄 작업 + LLM
  // ─────────────────────────────────────────────

  /** 일괄 커밋 (큐 발행) */
  batchCommit(repoIds: number[], message: string): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/batch-commit`, {
      method: 'POST',
      body: JSON.stringify({ repo_ids: repoIds, message }),
    });
  },

  /** 일괄 푸시 (큐 발행) */
  batchPush(repoIds: number[]): Promise<GitTaskResponse> {
    return request<GitTaskResponse>(`${BASE}/batch-push`, {
      method: 'POST',
      body: JSON.stringify({ repo_ids: repoIds }),
    });
  },

  /** LLM 커밋 메시지 자동 생성 */
  generateMessage(
    id: number,
    opts?: { provider?: string; model?: string }
  ): Promise<{ message: string; request_id: number; status?: string }> {
    return request(`${BASE}/${id}/generate-message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts ?? {}),
    });
  },

  /** 작업 이력 조회 */
  getOperations(id: number, limit = 50): Promise<OperationLog[]> {
    return request<OperationLog[]>(`${BASE}/${id}/operations?limit=${limit}`);
  },

  // ─────────────────────────────────────────────
  // 비동기 작업 결과 폴링
  // ─────────────────────────────────────────────

  /** 작업 결과 단일 조회 */
  getTaskResult(taskId: string): Promise<GitTaskResult> {
    return request<GitTaskResult>(`${BASE}/tasks/${taskId}`);
  },

  /**
   * 작업 발행 후 완료될 때까지 폴링.
   *
   * @param action - task를 발행하는 API 호출 함수
   * @param options - interval(ms, 기본 1000), maxRetries(기본 60)
   * @returns 완료된 GitTaskResult
   * @throws Error - maxRetries 초과 또는 failed 상태
   */
  async executeAndPoll(
    action: () => Promise<GitTaskResponse>,
    options?: { interval?: number; maxRetries?: number }
  ): Promise<GitTaskResult> {
    const interval = options?.interval ?? 1000;
    const maxRetries = options?.maxRetries ?? 60;

    const taskResponse = await action();
    const taskId = taskResponse.task_id;

    for (let i = 0; i < maxRetries; i++) {
      await new Promise((resolve) => setTimeout(resolve, interval));
      const result = await gitReposApi.getTaskResult(taskId);
      if (result.status !== 'pending') {
        return result;
      }
    }

    throw new Error(`작업 타임아웃: task_id=${taskId} (${maxRetries}회 폴링 초과)`);
  },
};
