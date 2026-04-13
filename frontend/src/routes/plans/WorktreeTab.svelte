<script lang="ts">
	import { onMount } from 'svelte';
	import { AlertTriangle, ChevronDown, ChevronUp, FileText, Lock } from 'lucide-svelte';
	import {
		devRunnerWorktreeApi,
		type BranchUnresolvedPlan,
		type MainDirtyStatus,
		type PlanOnlyBranch,
		type RepoOption,
		type WorktreeInfo
	} from '$lib/api/dev-runner';

	type WorktreePayload = {
		worktrees: WorktreeInfo[];
		plan_only: PlanOnlyBranch[];
		branch_unresolved: BranchUnresolvedPlan[];
		main_dirty: MainDirtyStatus;
	};

	let loading = $state(true);
	let error = $state('');
	let selectedRepoId = $state<number | null>(null);
	let showMainDirtyFiles = $state(false);

	let repos: RepoOption[] = $state([]);
	let worktreeData: WorktreePayload = $state({
		worktrees: [],
		plan_only: [],
		branch_unresolved: [],
		main_dirty: { dirty_count: 0, files: [] },
	});

	let expanded: Record<string, boolean> = $state({});

	const emptyWorktreeState: WorktreePayload = {
		worktrees: [],
		plan_only: [],
		branch_unresolved: [],
		main_dirty: { dirty_count: 0, files: [] },
	};

	onMount(async () => {
		await Promise.all([loadRepos(), loadWorktrees()]);
	});

	function sortByPlanMtimeDesc<T extends { plan_mtime: string | null }>(items: T[]): T[] {
		return [...items].sort((a, b) => {
			const aTime = a.plan_mtime ?? '';
			const bTime = b.plan_mtime ?? '';
			return bTime.localeCompare(aTime);
		});
	}

	async function loadRepos() {
		try {
			repos = await devRunnerWorktreeApi.listRepos();
		} catch {
			// /worktrees/repos는 보조 기능이며 실패해도 워크트리 조회는 계속 진행
			repos = [];
		}
	}

	async function loadWorktrees() {
		loading = true;
		error = '';
		showMainDirtyFiles = false;
		try {
			const data = await devRunnerWorktreeApi.listV2(selectedRepoId ?? undefined);
			worktreeData = {
				worktrees: data.worktrees ?? [],
				plan_only: data.plan_only ?? [],
				branch_unresolved: data.branch_unresolved ?? [],
				main_dirty: data.main_dirty ?? { dirty_count: 0, files: [] },
			};
			expanded = {};
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '워크트리 목록을 불러오지 못했습니다';
			worktreeData = emptyWorktreeState;
		} finally {
			loading = false;
		}
	}

	function handleRepoChange(event: Event) {
		const target = event.currentTarget as HTMLSelectElement;
		selectedRepoId = target.value ? Number(target.value) : null;
		loadWorktrees();
	}

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

	function repoLabel(repo: RepoOption): string {
		return repo.alias || repo.path.split(/[\\/]/).pop() || repo.path;
	}

	function toggleMainDirty() {
		showMainDirtyFiles = !showMainDirtyFiles;
	}
</script>

<div class="worktree-tab">
  <div class="worktree-toolbar">
    <div class="toolbar-title">워크트리 뷰</div>
    <div class="repo-select-wrap">
      <label for="worktree-repo-select" class="repo-label">레포지토리</label>
      <select
        id="worktree-repo-select"
        class="repo-select"
        value={selectedRepoId !== null ? String(selectedRepoId) : ''}
        on:change={handleRepoChange}
      >
        <option value="">현재 레포 (monitor-page)</option>
        {#each repos as repo}
          <option value={String(repo.id)}>{repoLabel(repo)}</option>
        {/each}
      </select>
    </div>
  </div>

	{#if loading}
		<div class="empty-state">불러오는 중...</div>
	{:else if error}
		<div class="error-state">{error}</div>
	{:else if worktreeData.worktrees.length === 0 && worktreeData.plan_only.length === 0 && worktreeData.branch_unresolved.length === 0 && worktreeData.main_dirty.dirty_count === 0}
		<div class="empty-state">워크트리 데이터가 없습니다</div>
	{:else}
		{#if worktreeData.main_dirty.dirty_count > 0}
			<section class="section-card">
				<div class="section-title section-title-row">
					<span class="section-title-main">
						<AlertTriangle size={13} />
						Main dirty ({worktreeData.main_dirty.dirty_count}건)
					</span>
					<button class="toggle-btn" onclick={toggleMainDirty} type="button">
						{showMainDirtyFiles ? '접기' : '펼치기'}
					</button>
				</div>
				{#if showMainDirtyFiles}
					<ul class="dirty-list">
						{#each worktreeData.main_dirty.files as file (file)}
							<li>{file}</li>
						{/each}
					</ul>
				{/if}
			</section>
		{/if}

		{#if worktreeData.worktrees.length > 0}
			<section class="section-card">
				<div class="section-title">활성 워크트리</div>
				<div class="worktree-list">
					{#each worktreeData.worktrees as wt (wt.branch)}
						<div class="worktree-card">
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
										<a class="plan-link" href="?tab=plans&subtab=plans" title={wt.plan_file}>
											<FileText size={13} />
											{planFileName(wt.plan_file)}
										</a>
									{/if}
									{#if wt.plan_mtime}
										<span class="plan-mtime">계획서 수정: {formatDate(wt.plan_mtime)}</span>
									{/if}
								</div>
							</div>

							<div class="commit-toggle">
								<button class="toggle-btn" onclick={() => toggleExpanded(wt.branch)} type="button">
									커밋 {wt.commits.length}개
									{#if expanded[wt.branch]}
										<ChevronUp size={14} />
									{:else}
										<ChevronDown size={14} />
									{/if}
								</button>
							</div>

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
			</section>
		{/if}

		{#if worktreeData.plan_only.length > 0}
			<section class="section-card">
				<div class="section-title">plan-only 브랜치</div>
				<div class="plan-list">
					{#each sortByPlanMtimeDesc(worktreeData.plan_only) as item (item.plan_file)}
						<div class="plan-item">
							<span class="plan-branch">{item.branch}</span>
							<a class="plan-link" href="?tab=plans&subtab=plans" title={item.plan_file}>
								<FileText size={12} />
								{planFileName(item.plan_file)}
							</a>
							{#if item.plan_mtime}
								<span class="plan-mtime">최종 수정: {formatDate(item.plan_mtime)}</span>
							{/if}
						</div>
					{/each}
				</div>
			</section>
		{/if}

		{#if worktreeData.branch_unresolved.length > 0}
			<section class="section-card">
				<div class="section-title">branch 미확정/매칭 실패 계획서</div>
				<div class="plan-list">
					{#each sortByPlanMtimeDesc(worktreeData.branch_unresolved) as item (item.plan_file)}
						<div class="plan-item">
							<span class="plan-warning">⚠ {item.reason}</span>
							<a class="plan-link" href="?tab=plans&subtab=plans" title={item.plan_file}>
								<FileText size={12} />
								{planFileName(item.plan_file)}
							</a>
							{#if item.plan_mtime}
								<span class="plan-mtime">최종 수정: {formatDate(item.plan_mtime)}</span>
							{/if}
						</div>
					{/each}
				</div>
			</section>
		{/if}
	{/if}
</div>

<style>
	.worktree-tab {
		padding: 0.75rem 0;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.worktree-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.toolbar-title {
		font-size: 0.9rem;
		font-weight: 600;
		color: var(--text-primary, #111827);
	}

	.repo-select-wrap {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.repo-label {
		font-size: 0.75rem;
		color: var(--text-muted, #6b7280);
	}

	.repo-select {
		border: 1px solid var(--border-color, #e5e7eb);
		border-radius: 0.375rem;
		padding: 0.25rem 0.5rem;
		background: var(--card-bg, #fff);
		color: var(--text-primary, #111827);
		font-size: 0.8125rem;
	}

	.section-card {
		border: 1px solid var(--border-color, #e5e7eb);
		border-radius: 0.5rem;
		padding: 0.75rem;
		background: var(--card-bg, #fff);
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.section-title {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text-primary, #111827);
	}

	.section-title-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
	}

	.section-title-main {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
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

	.dirty-list {
		margin: 0;
		padding-left: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.75rem;
		color: var(--text-primary, #111827);
		max-height: 11rem;
		overflow: auto;
	}

	.worktree-list,
	.plan-list {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.worktree-card {
		border: 1px solid var(--border-color, #e5e7eb);
		border-radius: 0.5rem;
		overflow: hidden;
		background: var(--card-bg, #f9fafb);
	}

	.card-header {
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border-color, #e5e7eb);
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
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

	.meta-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
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
		max-width: 300px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.plan-link:hover {
		text-decoration: underline;
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
	}

	.plan-item {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem 0.6rem;
		padding: 0.55rem 0.6rem;
		border: 1px solid var(--border-color, #e5e7eb);
		border-radius: 0.45rem;
		background: var(--badge-bg, #fafafa);
	}

	.plan-warning {
		color: var(--color-warning, #b45309);
		font-size: 0.75rem;
	}

	.plan-branch {
		font-family: monospace;
		font-size: 0.75rem;
		color: var(--text-primary, #111827);
		background: var(--code-bg, #f3f4f6);
		border-radius: 0.25rem;
		padding: 0.05rem 0.35rem;
	}
</style>
