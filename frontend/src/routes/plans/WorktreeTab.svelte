<script lang="ts">
  import { onMount } from 'svelte';
  import { AlertTriangle, ChevronDown, ChevronUp, FileText, Lock } from 'lucide-svelte';
  import {
    devRunnerWorktreeApi,
    type WorktreeInfo,
    type WorktreeCommit,
    type WorktreeListResponse,
    type PlanOnlyBranch,
    type RepoOption,
  } from '$lib/api/dev-runner';

  const EMPTY_RESPONSE: WorktreeListResponse = {
    worktrees: [],
    plan_only: [],
    branch_unresolved: [],
    main_dirty: { dirty_count: 0, files: [] },
  };

  let response: WorktreeListResponse = $state(EMPTY_RESPONSE);
  let repos: RepoOption[] = $state([]);
  let selectedRepoId: number | undefined = $state(undefined);
  let loading = $state(true);
  let error = $state('');
  let showDirtyFiles = $state(false);

  // 커밋 목록 펼치기/접기 상태 (branch → boolean)
  let expanded: Record<string, boolean> = $state({});

  async function loadWorktrees() {
    loading = true;
    error = '';
    try {
      response = await devRunnerWorktreeApi.listV2(selectedRepoId);
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : '워크트리 목록을 불러오지 못했습니다';
      response = EMPTY_RESPONSE;
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    const [_, repoList] = await Promise.allSettled([
      loadWorktrees(),
      devRunnerWorktreeApi.listRepos(),
    ]);
    if (repoList.status === 'fulfilled') {
      repos = repoList.value;
    }
  });

  function toggleExpanded(branch: string) {
    expanded[branch] = !expanded[branch];
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function planFileName(planFile: string | null): string {
    if (!planFile) return '';
    return planFile.split(/[\\/]/).pop() ?? planFile;
  }
</script>

<div class="worktree-tab">
  <!-- 레포 선택 드롭다운 -->
  <div class="toolbar">
    <select
      class="repo-select"
      bind:value={selectedRepoId}
      onchange={loadWorktrees}
    >
      <option value={undefined}>현재 레포 (monitor-page)</option>
      {#each repos as repo (repo.id)}
        <option value={repo.id}>{repo.alias}</option>
      {/each}
    </select>
  </div>

  {#if loading}
    <div class="empty-state">불러오는 중...</div>
  {:else if error}
    <div class="error-state">{error}</div>
  {:else}
    <!-- main dirty 배너 -->
    {#if response.main_dirty.dirty_count > 0}
      <div class="dirty-banner">
        <button
          class="dirty-banner-btn"
          type="button"
          onclick={() => (showDirtyFiles = !showDirtyFiles)}
        >
          <AlertTriangle size={14} />
          main: {response.main_dirty.dirty_count}개 파일 미커밋
          {#if showDirtyFiles}
            <ChevronUp size={14} />
          {:else}
            <ChevronDown size={14} />
          {/if}
        </button>
        {#if showDirtyFiles}
          <div class="dirty-file-list">
            {#each response.main_dirty.files as file (file)}
              <code class="dirty-file">{file}</code>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- 워크트리 목록 -->
    {#if response.worktrees.length === 0 && response.plan_only.length === 0 && response.branch_unresolved.length === 0}
      <div class="empty-state">활성 워크트리가 없습니다</div>
    {:else}
      <div class="worktree-list">
        {#each response.worktrees as wt (wt.branch)}
          <div class="worktree-card">
            <!-- 카드 헤더 -->
            <div class="card-header">
              <div class="branch-row">
                <span class="branch-name">{wt.branch}</span>
                <div class="badges">
                  <span class="badge badge-diff">+{wt.ahead} -{wt.behind}</span>
                  {#if wt.locked}
                    <span class="badge badge-locked" title="locked">
                      <Lock size={11} />
                      locked
                    </span>
                  {/if}
                </div>
              </div>
              <div class="meta-row">
                <span class="created-at">생성: {formatDate(wt.created_at)}</span>
                {#if wt.plan_file}
                  <a
                    class="plan-link"
                    href="?tab=plans&subtab=plans"
                    title={wt.plan_file}
                  >
                    <FileText size={13} />
                    {planFileName(wt.plan_file)}
                  </a>
                  {#if wt.plan_mtime}
                    <span class="plan-mtime">수정: {formatDate(wt.plan_mtime)}</span>
                  {/if}
                {/if}
              </div>
            </div>

            <!-- 커밋 토글 -->
            <div class="commit-toggle">
              <button
                class="toggle-btn"
                onclick={() => toggleExpanded(wt.branch)}
                type="button"
              >
                커밋 {wt.commits.length}개
                {#if expanded[wt.branch]}
                  <ChevronUp size={14} />
                {:else}
                  <ChevronDown size={14} />
                {/if}
              </button>
            </div>

            <!-- 커밋 목록 -->
            {#if expanded[wt.branch]}
              <div class="commit-list">
                {#each wt.commits as commit (commit.hash)}
                  <div class="commit-row">
                    <div class="commit-header">
                      <code class="short-hash">{commit.short_hash}</code>
                      <span class="commit-message">{commit.message}</span>
                      <span class="commit-date">{formatDate(commit.date)}</span>
                    </div>
                    {#if commit.diff_stat.length > 0}
                      <div class="diff-stat-list">
                        {#each commit.diff_stat.slice(0, 5) as stat (stat.file)}
                          <div class="diff-stat-row">
                            <span class="diff-file">{stat.file}</span>
                            <span class="diff-changes">{stat.changes}</span>
                          </div>
                        {/each}
                        {#if commit.diff_stat.length > 5}
                          <div class="diff-more">외 {commit.diff_stat.length - 5}개 파일</div>
                        {/if}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <!-- plan-only 섹션 -->
      {#if response.plan_only.length > 0}
        <div class="section-header">워크트리 없는 계획서</div>
        <div class="worktree-list">
          {#each response.plan_only as po (po.plan_file)}
            <div class="worktree-card plan-only-card">
              <div class="card-header">
                <div class="branch-row">
                  <span class="branch-name">{po.branch}</span>
                  <span class="badge badge-plan-only">워크트리 없음</span>
                </div>
                <div class="meta-row">
                  <a
                    class="plan-link"
                    href="?tab=plans&subtab=plans"
                    title={po.plan_file}
                  >
                    <FileText size={13} />
                    {planFileName(po.plan_file)}
                  </a>
                  {#if po.plan_mtime}
                    <span class="plan-mtime">수정: {formatDate(po.plan_mtime)}</span>
                  {/if}
                </div>
              </div>
            </div>
          {/each}
        </div>
      {/if}

      <!-- branch_unresolved 섹션 -->
      {#if response.branch_unresolved.length > 0}
        <div class="section-header">브랜치 헤더 누락 계획서</div>
        <div class="worktree-list">
          {#each response.branch_unresolved as bu (bu.plan_file)}
            <div class="worktree-card unresolved-card">
              <div class="card-header">
                <div class="branch-row">
                  <span class="branch-name unresolved-name">{planFileName(bu.plan_file)}</span>
                  <span class="badge badge-unresolved">헤더 없음</span>
                </div>
                <div class="meta-row">
                  {#if bu.plan_mtime}
                    <span class="plan-mtime">수정: {formatDate(bu.plan_mtime)}</span>
                  {/if}
                  <span class="unresolved-reason">{bu.reason}</span>
                </div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .worktree-tab {
    padding: 0.75rem 0;
  }

  .toolbar {
    margin-bottom: 0.75rem;
  }

  .repo-select {
    font-size: 0.875rem;
    padding: 0.375rem 0.5rem;
    border: 1px solid var(--border-color, #e5e7eb);
    border-radius: 0.375rem;
    background: var(--card-bg, #fff);
    color: var(--text-primary, #111827);
    cursor: pointer;
  }

  .dirty-banner {
    margin-bottom: 0.75rem;
    border: 1px solid #f59e0b;
    border-radius: 0.5rem;
    background: #fffbeb;
    overflow: hidden;
  }

  .dirty-banner-btn {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    width: 100%;
    padding: 0.5rem 0.75rem;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.8125rem;
    color: #92400e;
    text-align: left;
  }

  .dirty-banner-btn:hover {
    background: #fef3c7;
  }

  .dirty-file-list {
    padding: 0.25rem 0.75rem 0.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
    border-top: 1px solid #f59e0b;
  }

  .dirty-file {
    font-size: 0.75rem;
    font-family: monospace;
    color: #78350f;
  }

  .empty-state,
  .error-state {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted, #6b7280);
    font-size: 0.875rem;
  }

  .error-state {
    color: var(--color-error, #ef4444);
  }

  .section-header {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--text-secondary, #374151);
    margin-top: 1.25rem;
    margin-bottom: 0.5rem;
    padding-bottom: 0.25rem;
    border-bottom: 1px solid var(--border-color, #e5e7eb);
  }

  .worktree-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .worktree-card {
    border: 1px solid var(--border-color, #e5e7eb);
    border-radius: 0.5rem;
    overflow: hidden;
    background: var(--card-bg, #fff);
  }

  .plan-only-card {
    background: var(--bg-subtle, #f9fafb);
    border-color: var(--border-subtle, #d1d5db);
  }

  .unresolved-card {
    background: #fffbeb;
    border-color: #fcd34d;
  }

  .card-header {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color, #e5e7eb);
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .plan-only-card .card-header,
  .unresolved-card .card-header {
    border-bottom: none;
  }

  .branch-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .branch-name {
    font-family: monospace;
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--text-primary, #111827);
  }

  .unresolved-name {
    color: var(--text-secondary, #374151);
  }

  .badges {
    display: flex;
    gap: 0.375rem;
    align-items: center;
  }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.125rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .badge-diff {
    background: var(--badge-diff-bg, #dbeafe);
    color: var(--badge-diff-text, #1d4ed8);
  }

  .badge-locked {
    background: var(--badge-locked-bg, #fef3c7);
    color: var(--badge-locked-text, #92400e);
  }

  .badge-plan-only {
    background: #f3f4f6;
    color: #6b7280;
  }

  .badge-unresolved {
    background: #fef3c7;
    color: #92400e;
  }

  .meta-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .created-at {
    font-size: 0.75rem;
    color: var(--text-muted, #6b7280);
  }

  .plan-link {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.75rem;
    color: var(--color-link, #3b82f6);
    text-decoration: none;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .plan-link:hover {
    text-decoration: underline;
  }

  .plan-mtime {
    font-size: 0.75rem;
    color: var(--text-muted, #6b7280);
  }

  .unresolved-reason {
    font-size: 0.75rem;
    color: #92400e;
    font-style: italic;
  }

  .commit-toggle {
    padding: 0.375rem 1rem;
  }

  .toggle-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.8125rem;
    color: var(--text-secondary, #374151);
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.25rem 0;
  }

  .toggle-btn:hover {
    color: var(--color-link, #3b82f6);
  }

  .commit-list {
    border-top: 1px solid var(--border-color, #e5e7eb);
    padding: 0.5rem 0;
  }

  .commit-row {
    padding: 0.375rem 1rem;
  }

  .commit-row + .commit-row {
    border-top: 1px solid var(--border-subtle, #f3f4f6);
  }

  .commit-header {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .short-hash {
    font-family: monospace;
    font-size: 0.75rem;
    color: var(--text-muted, #6b7280);
    background: var(--code-bg, #f3f4f6);
    padding: 0.0625rem 0.25rem;
    border-radius: 0.25rem;
    flex-shrink: 0;
  }

  .commit-message {
    font-size: 0.8125rem;
    color: var(--text-primary, #111827);
    flex: 1;
    min-width: 0;
  }

  .commit-date {
    font-size: 0.75rem;
    color: var(--text-muted, #6b7280);
    flex-shrink: 0;
  }

  .diff-stat-list {
    margin-top: 0.25rem;
    padding-left: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
  }

  .diff-stat-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
  }

  .diff-file {
    font-family: monospace;
    color: var(--text-secondary, #374151);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 300px;
  }

  .diff-changes {
    color: var(--text-muted, #6b7280);
    flex-shrink: 0;
  }

  .diff-more {
    font-size: 0.75rem;
    color: var(--text-muted, #6b7280);
    padding-left: 0;
  }
</style>
