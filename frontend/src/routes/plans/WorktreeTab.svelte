<script lang="ts">
  import { onMount } from 'svelte';
  import {
    AlertTriangle,
    Archive,
    ChevronDown,
    ChevronUp,
    FileText,
    FlaskConical,
    Lock,
    Trash2,
  } from 'lucide-svelte';
  import {
    devRunnerWorktreeApi,
    type WorktreeCommit,
    type WorktreeCleanupResponse,
    type WorktreeListResponse,
    type RepoOption,
  } from '$lib/api/dev-runner';
  import { toast } from '$lib/stores/toast';
  import { createSelection } from '$lib/utils/selection.svelte';

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
  let hideTestRunners = $state(true);
  let cleanableOnly = $state(false);
  let cleanupBusy = $state(false);
  let cleanupResult: WorktreeCleanupResponse | null = $state(null);

  let expanded: Record<string, boolean> = $state({});
  let commitsByBranch: Record<string, WorktreeCommit[]> = $state({});
  let loadingCommits: Record<string, boolean> = $state({});
  let commitsError: Record<string, string> = $state({});
  let loadRequestSeq = 0;
  let commitRequestSeq = 0;
  let branchRequestSeq: Record<string, number> = $state({});
  const selection = createSelection<string>();

  const visibleWorktrees = $derived(
    response.worktrees.filter(
      (wt) => (!hideTestRunners || !wt.is_test) && (!cleanableOnly || wt.cleanable)
    )
  );
  const visiblePlanOnly = $derived(
    response.plan_only.filter((po) => !hideTestRunners || !po.is_test)
  );
  const visibleBranchUnresolved = $derived(
    response.branch_unresolved.filter((bu) => !hideTestRunners || !bu.is_test)
  );
  const visibleCleanableBranches = $derived(
    visibleWorktrees.filter((wt) => wt.cleanable).map((wt) => wt.branch)
  );
  const hiddenTestCount = $derived(
    hideTestRunners
      ? response.worktrees.filter((wt) => wt.is_test).length
        + response.plan_only.filter((po) => po.is_test).length
        + response.branch_unresolved.filter((bu) => bu.is_test).length
      : 0
  );

  function resetWorktreeUiState() {
    expanded = {};
    commitsByBranch = {};
    loadingCommits = {};
    commitsError = {};
    branchRequestSeq = {};
    cleanupResult = null;
    selection.clear();
  }

  function hasVisibleBranch(branch: string): boolean {
    return response.worktrees.some((wt) => wt.branch === branch);
  }

  async function loadWorktrees() {
    const requestId = ++loadRequestSeq;
    resetWorktreeUiState();
    loading = true;
    error = '';
    try {
      const nextResponse = await devRunnerWorktreeApi.listV2(selectedRepoId);
      if (requestId !== loadRequestSeq) return;
      response = nextResponse;
    } catch (e: unknown) {
      if (requestId !== loadRequestSeq) return;
      error = e instanceof Error ? e.message : '워크트리 목록을 불러오지 못했습니다';
      response = EMPTY_RESPONSE;
    } finally {
      if (requestId === loadRequestSeq) {
        loading = false;
      }
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

  async function loadBranchCommits(branch: string) {
    if (loadingCommits[branch] || commitsByBranch[branch]) {
      return;
    }

    const requestId = ++commitRequestSeq;
    const requestRepoId = selectedRepoId ?? null;
    branchRequestSeq[branch] = requestId;
    loadingCommits[branch] = true;
    commitsError[branch] = '';

    const isCurrentRequest = () =>
      branchRequestSeq[branch] === requestId
      && (selectedRepoId ?? null) === requestRepoId
      && hasVisibleBranch(branch);

    try {
      const commits = await devRunnerWorktreeApi.listCommits(branch, selectedRepoId);
      if (!isCurrentRequest()) return;
      commitsByBranch[branch] = commits;
    } catch (e: unknown) {
      if (!isCurrentRequest()) return;
      commitsError[branch] = e instanceof Error ? e.message : '커밋을 불러오지 못했습니다';
    } finally {
      if (isCurrentRequest()) {
        loadingCommits[branch] = false;
      }
    }
  }

  function toggleExpanded(branch: string) {
    const nextExpanded = !expanded[branch];
    expanded[branch] = nextExpanded;
    if (nextExpanded) {
      void loadBranchCommits(branch);
    }
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

  function cleanupSummaryText(result: WorktreeCleanupResponse): string {
    const removable = result.results.filter((item) => item.reason === 'dry_run').map((item) => item.branch);
    const blocked = result.results.filter((item) => item.reason !== 'dry_run');
    const lines = [
      `정리 후보 ${removable.length}개를 제거합니다.`,
      removable.slice(0, 12).map((branch) => `- ${branch}`).join('\n'),
    ];
    if (removable.length > 12) {
      lines.push(`... 외 ${removable.length - 12}개`);
    }
    if (blocked.length > 0) {
      lines.push('');
      lines.push(`건너뜀 ${blocked.length}개`);
      lines.push(
        blocked
          .slice(0, 8)
          .map((item) => `- ${item.branch}: ${item.reason || item.status}`)
          .join('\n')
      );
    }
    return lines.filter(Boolean).join('\n');
  }

  async function handleBatchCleanup() {
    const branches = selection.toArray();
    if (branches.length === 0) return;

    cleanupBusy = true;
    cleanupResult = null;
    try {
      const preview = await devRunnerWorktreeApi.cleanup(
        { branches, dry_run: true },
        selectedRepoId,
      );
      cleanupResult = preview;

      const removable = preview.results.filter((item) => item.reason === 'dry_run');
      if (removable.length === 0) {
        toast.warning('정리 가능한 워크트리가 없습니다.');
        return;
      }
      if (!confirm(cleanupSummaryText(preview))) {
        return;
      }

      const result = await devRunnerWorktreeApi.cleanup(
        { branches, dry_run: false },
        selectedRepoId,
      );
      cleanupResult = result;
      selection.clear();
      await loadWorktrees();

      const removed = result.summary.removed ?? 0;
      const failed = result.summary.failed ?? 0;
      const skipped = result.summary.skipped ?? 0;
      if (removed > 0) {
        toast.success(`워크트리 ${removed}개를 정리했습니다.`);
      }
      if (failed > 0 || skipped > 0) {
        toast.warning(`건너뜀 ${skipped}개, 실패 ${failed}개가 있습니다.`);
      }
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : '워크트리 정리에 실패했습니다';
      cleanupResult = null;
      toast.error(message);
    } finally {
      cleanupBusy = false;
    }
  }

  function cleanupStatusClass(status: string): string {
    switch (status) {
      case 'removed':
        return 'result-removed';
      case 'failed':
        return 'result-failed';
      default:
        return 'result-skipped';
    }
  }
</script>

<div class="worktree-tab">
  <div class="toolbar">
    <div class="toolbar-left">
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

      <label class="filter-check">
        <input type="checkbox" bind:checked={hideTestRunners} />
        테스트 러너 숨김
      </label>

      <label class="filter-check">
        <input type="checkbox" bind:checked={cleanableOnly} />
        정리가능만 보기
      </label>
    </div>

    <div class="toolbar-right">
      <button
        type="button"
        class="toolbar-btn"
        onclick={() => selection.selectAll(visibleCleanableBranches)}
        disabled={cleanupBusy || visibleCleanableBranches.length === 0}
      >
        {selection.isAllSelected(visibleCleanableBranches) ? '전체 해제' : '전체 선택'}
      </button>
      <button
        type="button"
        class="toolbar-btn toolbar-btn-danger"
        onclick={handleBatchCleanup}
        disabled={cleanupBusy || selection.count === 0}
      >
        {cleanupBusy ? '정리 중...' : `일괄 정리 (${selection.count})`}
      </button>
    </div>
  </div>

  {#if hiddenTestCount > 0}
    <div class="filter-hint">테스트 항목 {hiddenTestCount}개가 숨겨져 있습니다.</div>
  {/if}

  {#if cleanupResult}
    <div class="cleanup-result">
      <div class="cleanup-summary">
        요청 {cleanupResult.summary.requested ?? 0} · 제거 {cleanupResult.summary.removed ?? 0} · 건너뜀 {cleanupResult.summary.skipped ?? 0} · 실패 {cleanupResult.summary.failed ?? 0}
      </div>
      <div class="cleanup-result-list">
        {#each cleanupResult.results as item (`${item.branch}-${item.status}-${item.reason}`)}
          <div class={`cleanup-result-row ${cleanupStatusClass(item.status)}`}>
            <code>{item.branch}</code>
            <span>{item.reason || item.status}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  {#if loading}
    <div class="empty-state">불러오는 중...</div>
  {:else if error}
    <div class="error-state">{error}</div>
  {:else}
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

    {#if visibleWorktrees.length === 0 && visiblePlanOnly.length === 0 && visibleBranchUnresolved.length === 0}
      <div class="empty-state">표시할 워크트리가 없습니다</div>
    {:else}
      <div class="worktree-list">
        {#each visibleWorktrees as wt (wt.branch)}
          <div class={`worktree-card ${wt.cleanable ? 'worktree-card-cleanable' : ''}`}>
            <div class="card-header">
              <div class="card-main">
                <label class="select-cell">
                  <input
                    type="checkbox"
                    checked={selection.has(wt.branch)}
                    disabled={!wt.cleanable || cleanupBusy}
                    onchange={() => selection.toggle(wt.branch)}
                  />
                </label>

                <div class="card-body">
                  <div class="branch-row">
                    <span class="branch-name">{wt.branch}</span>
                    <div class="badges">
                      <span class="badge badge-diff">+{wt.ahead} -{wt.behind}</span>
                      {#if wt.cleanable}
                        <span class="badge badge-cleanable">
                          <Trash2 size={11} />
                          정리가능
                        </span>
                      {/if}
                      {#if wt.is_test}
                        <span class="badge badge-test">
                          <FlaskConical size={11} />
                          테스트
                        </span>
                      {/if}
                      {#if wt.plan_file_archived}
                        <span class="badge badge-archive">
                          <Archive size={11} />
                          archive
                        </span>
                      {/if}
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
                        {wt.plan_file_archived ? `archive: ${planFileName(wt.plan_file)}` : planFileName(wt.plan_file)}
                      </a>
                      {#if wt.plan_mtime}
                        <span class="plan-mtime">수정: {formatDate(wt.plan_mtime)}</span>
                      {/if}
                    {:else}
                      <span class="plan-mtime">연결된 계획서 없음</span>
                    {/if}
                  </div>
                </div>
              </div>
            </div>

            <div class="commit-toggle">
              <button
                class="toggle-btn"
                onclick={() => toggleExpanded(wt.branch)}
                type="button"
              >
                커밋 {wt.commit_count}개
                {#if expanded[wt.branch]}
                  <ChevronUp size={14} />
                {:else}
                  <ChevronDown size={14} />
                {/if}
              </button>
            </div>

            {#if expanded[wt.branch]}
              <div class="commit-list">
                {#if loadingCommits[wt.branch]}
                  <div class="commit-state">커밋을 불러오는 중...</div>
                {:else if commitsError[wt.branch]}
                  <div class="commit-state commit-state-error">{commitsError[wt.branch]}</div>
                {:else if (commitsByBranch[wt.branch]?.length ?? 0) === 0}
                  <div class="commit-state">표시할 커밋이 없습니다.</div>
                {:else}
                  {#each commitsByBranch[wt.branch] ?? [] as commit (commit.hash)}
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
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>

      {#if visiblePlanOnly.length > 0}
        <div class="section-header">워크트리 없는 계획서</div>
        <div class="worktree-list">
          {#each visiblePlanOnly as po (po.plan_file)}
            <div class="worktree-card plan-only-card">
              <div class="card-header card-header-static">
                <div class="branch-row">
                  <span class="branch-name">{po.branch}</span>
                  <div class="badges">
                    <span class="badge badge-plan-only">워크트리 없음</span>
                    {#if po.is_test}
                      <span class="badge badge-test">
                        <FlaskConical size={11} />
                        테스트
                      </span>
                    {/if}
                  </div>
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

      {#if visibleBranchUnresolved.length > 0}
        <div class="section-header">브랜치 헤더 누락 계획서</div>
        <div class="worktree-list">
          {#each visibleBranchUnresolved as bu (bu.plan_file)}
            <div class="worktree-card unresolved-card">
              <div class="card-header card-header-static">
                <div class="branch-row">
                  <span class="branch-name unresolved-name">{planFileName(bu.plan_file)}</span>
                  <div class="badges">
                    <span class="badge badge-unresolved">헤더 없음</span>
                    {#if bu.is_test}
                      <span class="badge badge-test">
                        <FlaskConical size={11} />
                        테스트
                      </span>
                    {/if}
                  </div>
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
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .toolbar-left,
  .toolbar-right {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .repo-select,
  .toolbar-btn {
    font-size: 0.875rem;
    padding: 0.375rem 0.625rem;
    border: 1px solid var(--border-color, #e5e7eb);
    border-radius: 0.375rem;
    background: var(--card-bg, #fff);
    color: var(--text-primary, #111827);
  }

  .toolbar-btn {
    cursor: pointer;
  }

  .toolbar-btn:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .toolbar-btn-danger {
    border-color: #f59e0b;
    background: #fff7ed;
    color: #9a3412;
  }

  .filter-check {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    font-size: 0.8125rem;
    color: var(--text-secondary, #374151);
  }

  .filter-hint {
    margin-bottom: 0.75rem;
    font-size: 0.75rem;
    color: var(--text-muted, #6b7280);
  }

  .cleanup-result {
    margin-bottom: 0.75rem;
    border: 1px solid var(--border-color, #e5e7eb);
    border-radius: 0.5rem;
    background: var(--card-bg, #fff);
    padding: 0.75rem;
  }

  .cleanup-summary {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--text-secondary, #374151);
    margin-bottom: 0.5rem;
  }

  .cleanup-result-list {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .cleanup-result-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    font-size: 0.75rem;
    border-radius: 0.375rem;
    padding: 0.375rem 0.5rem;
  }

  .result-removed {
    background: #ecfdf5;
    color: #166534;
  }

  .result-skipped {
    background: #f3f4f6;
    color: #4b5563;
  }

  .result-failed {
    background: #fef2f2;
    color: #b91c1c;
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

  .worktree-card-cleanable {
    border-color: #bbf7d0;
    box-shadow: inset 0 0 0 1px #dcfce7;
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
  }

  .card-header-static {
    border-bottom: none;
  }

  .card-main {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
  }

  .card-body {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .select-cell {
    padding-top: 0.125rem;
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
    flex-wrap: wrap;
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

  .badge-cleanable {
    background: #dcfce7;
    color: #166534;
  }

  .badge-test {
    background: #f3f4f6;
    color: #4b5563;
  }

  .badge-archive {
    background: #dbeafe;
    color: #1d4ed8;
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

  .created-at,
  .plan-mtime {
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
    max-width: 320px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .plan-link:hover {
    text-decoration: underline;
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

  .commit-state {
    padding: 0.5rem 1rem;
    font-size: 0.8125rem;
    color: var(--text-muted, #6b7280);
  }

  .commit-state-error {
    color: var(--color-error, #dc2626);
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

  .diff-changes,
  .diff-more {
    color: var(--text-muted, #6b7280);
    flex-shrink: 0;
  }

  @media (max-width: 768px) {
    .toolbar {
      align-items: stretch;
    }

    .toolbar-left,
    .toolbar-right {
      width: 100%;
    }

    .toolbar-right .toolbar-btn,
    .repo-select {
      flex: 1;
    }

    .cleanup-result-row,
    .card-main {
      flex-direction: column;
      align-items: flex-start;
    }

    .select-cell {
      padding-top: 0;
    }
  }
</style>
