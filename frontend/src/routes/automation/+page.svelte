<script lang="ts">
	import { page } from '$app/stores';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import { devRunnerPlanApi } from '$lib/api/dev-runner';
	import { search as fileSearchSearch, pollSearchResult as pollFileSearchResult } from '$lib/api/fileSearch';
	import type { FileMatch } from '$lib/types/fileSearch';
	import DevRunnerTab from './DevRunnerTab.svelte';
	import GitReposTab from './GitReposTab.svelte';
	import DailyReportTab from './DailyReportTab.svelte';
	import TrackingTab from './TrackingTab.svelte';
	import PlanListTab from '../plans/PlanListTab.svelte';
	import ArchiveTab from '../plans/ArchiveTab.svelte';
	import HistoryTab from '../plans/HistoryTab.svelte';
	import WorktreeTab from '../plans/WorktreeTab.svelte';

	type MainTab = 'dev-runner' | 'git-repos' | 'plans' | 'daily-report' | 'tracking';
	let mainTab = $state<MainTab>('dev-runner');
	let initialPlan = $state('');
	let initialRunner = $state('');

	// plans 서브탭
	type PlansSubTab = 'plans' | 'archive' | 'history' | 'worktrees';
	let plansSubTab: PlansSubTab = $state('plans');
	let focusPath = $state<string | null>(null);

	let quickQuery = $state('');
	let quickLoading = $state(false);
	let quickPollStatus = $state('');
	let quickError = $state('');
	let quickResults: FileMatch[] = $state([]);
	let quickScopePaths: string[] = $state([]);
	let quickScopeLoaded = $state(false);
	let quickAbort: AbortController | null = null;

	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		const subParam = $page.url.searchParams.get('subtab') as PlansSubTab | null;
		const hasValidPlansSubtab = !!(subParam && ['plans', 'archive', 'history', 'worktrees'].includes(subParam));
		if (tabParam === 'git-repos') {
			mainTab = 'git-repos';
		} else if (tabParam === 'tracking') {
			mainTab = 'tracking';
		} else if (tabParam === 'daily-report') {
			mainTab = 'daily-report';
		} else if (tabParam === 'plans' || (!tabParam && hasValidPlansSubtab)) {
			mainTab = 'plans';
			plansSubTab = hasValidPlansSubtab ? subParam! : 'plans';
		} else {
			mainTab = 'dev-runner';
		}
		initialPlan = $page.url.searchParams.get('plan') ?? '';
		initialRunner = $page.url.searchParams.get('runner') ?? '';
	});

	const autoTabs = [
		{ id: 'dev-runner', label: 'Dev Runner' },
		{ id: 'git-repos', label: 'Git 관리' },
		{ id: 'plans', label: '계획서' },
		{ id: 'tracking', label: 'Tracking' },
		{ id: 'daily-report', label: '일일 보고서' },
	];

	const plansSubTabs = [
		{ id: 'plans', label: '계획' },
		{ id: 'archive', label: '아카이브' },
		{ id: 'history', label: '이력' },
		{ id: 'worktrees', label: '워크트리' },
	];

	const pageTitle = $derived(
		mainTab === 'git-repos' ? 'Git 관리' :
		mainTab === 'plans' ? '계획서 관리' :
		mainTab === 'tracking' ? 'Tracking' :
		mainTab === 'daily-report' ? '일일 보고서' :
		'개발 작업'
	);

	function isArchivePath(path: string) {
		return path.includes('/docs/archive/') || path.includes('\\docs\\archive\\');
	}

	async function loadQuickScopeIfNeeded() {
		if (quickScopeLoaded) return;
		quickError = '';
		try {
			const paths = await devRunnerPlanApi.listPaths();
			quickScopePaths = paths
				.filter((p) => p.path_type === 'plan' || p.path_type === 'archive')
				.map((p) => p.path);
			quickScopeLoaded = true;
		} catch (e) {
			quickError = e instanceof Error ? e.message : '계획서 검색 경로를 불러오지 못했습니다.';
		}
	}

	async function runQuickSearch() {
		if (!quickQuery.trim() || quickLoading) return;

		await loadQuickScopeIfNeeded();
		if (quickScopePaths.length === 0) {
			quickError = quickError || '등록된 plan/archive 경로가 없습니다.';
			return;
		}

		quickAbort?.abort();
		quickAbort = new AbortController();

		quickLoading = true;
		quickPollStatus = '';
		quickError = '';
		quickResults = [];

		try {
			const accepted = await fileSearchSearch(
				{
					query: quickQuery.trim(),
					origin: 'plan-quick',
					mode: 'both',
					regex: false,
					case_sensitive: false,
					paths: quickScopePaths,
					extensions: ['md'],
					excludes: [],
					max_results: 50,
					context_lines: 2
				},
				quickAbort.signal
			);

			quickPollStatus = accepted.status;

			let attempts = 0;
			while (!quickAbort.signal.aborted) {
				const poll = await pollFileSearchResult(accepted.search_id);
				quickPollStatus = poll.status;

				if (poll.status === 'completed') {
					quickResults = poll.result?.results ?? [];
					break;
				}
				if (poll.status === 'failed') {
					quickError = poll.error_message ?? '검색 중 오류가 발생했습니다.';
					break;
				}

				await new Promise((r) => setTimeout(r, 200));
				attempts += 1;
				if (attempts > 300) {
					quickError = '검색 시간이 초과되었습니다.';
					break;
				}
			}
		} catch (e) {
			if (e instanceof Error && e.name === 'AbortError') return;
			quickError = e instanceof Error ? e.message : '검색 요청 실패';
		} finally {
			quickLoading = false;
			quickPollStatus = '';
		}
	}

	function openQuickResult(filePath: string) {
		focusPath = filePath;
		plansSubTab = isArchivePath(filePath) ? 'archive' : 'plans';
	}

	$effect(() => {
		if (mainTab === 'plans') {
			void loadQuickScopeIfNeeded();
		}
	});
</script>

<svelte:head>
	<title>{pageTitle} | Monitor Page</title>
</svelte:head>

{#snippet plansToolbar()}
	<div class="rounded-lg border border-border bg-card px-3 py-2 space-y-2">
		<div class="flex flex-wrap items-center gap-2">
			<input
				bind:value={quickQuery}
				type="text"
				placeholder="plan/archive 빠른 검색..."
				class="flex-1 min-w-[14rem] rounded-md border border-border bg-background px-3 py-2 text-sm
					   shadow-sm outline-none transition-colors
					   focus:border-primary focus:ring-2 focus:ring-primary/20"
				onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void runQuickSearch(); } }}
				disabled={quickLoading}
			/>
			<button
				onclick={() => runQuickSearch()}
				disabled={!quickQuery.trim() || quickLoading}
				class="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground
					   shadow-sm transition-colors hover:bg-primary/90
					   disabled:cursor-not-allowed disabled:opacity-50"
			>
				검색
			</button>
		</div>

		{#if quickError}
			<div class="text-xs text-destructive">{quickError}</div>
		{:else if quickLoading && quickPollStatus}
			<div class="text-xs text-muted-foreground">검색 중... ({quickPollStatus})</div>
		{/if}

		{#if quickResults.length > 0}
			<div class="max-h-[220px] overflow-auto rounded-md border border-border bg-background">
				{#each quickResults as r (r.file_path)}
					<button
						onclick={() => openQuickResult(r.file_path)}
						class="w-full border-b border-border/50 px-3 py-2 text-left text-sm transition-colors last:border-b-0 hover:bg-muted/40"
					>
						<div class="font-medium truncate">{r.file_name}</div>
						<div class="text-xs text-muted-foreground truncate">{r.file_path}</div>
					</button>
				{/each}
			</div>
		{:else if !quickLoading && quickQuery.trim()}
			<div class="text-xs text-muted-foreground">검색 결과가 없습니다.</div>
		{/if}
	</div>
{/snippet}

<TabbedPageLayout
	title={pageTitle}
	primaryTabs={autoTabs}
	bind:activePrimaryTab={mainTab}
	primaryQueryParam="tab"
	secondaryTabs={mainTab === 'plans' ? plansSubTabs : []}
	bind:activeSecondaryTab={plansSubTab}
	secondaryQueryParam="subtab"
	toolbar={mainTab === 'plans' ? plansToolbar : undefined}
	density="compact"
	containerClass="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-4 lg:p-6"
	contentClass="min-h-0 flex-1 overflow-hidden"
>
	<div class="flex-1 overflow-hidden">
		{#if mainTab === 'dev-runner'}
			<DevRunnerTab {initialPlan} {initialRunner} />
		{:else if mainTab === 'git-repos'}
			<div class="overflow-auto h-full">
				<GitReposTab />
			</div>
		{:else if mainTab === 'plans'}
			<div class="flex h-full flex-col overflow-hidden">
				<div class="flex-1 overflow-auto">
					{#if plansSubTab === 'plans'}
						<PlanListTab {focusPath} onFocusConsumed={() => (focusPath = null)} />
					{:else if plansSubTab === 'archive'}
						<ArchiveTab {focusPath} onFocusConsumed={() => (focusPath = null)} />
					{:else if plansSubTab === 'history'}
						<HistoryTab />
					{:else if plansSubTab === 'worktrees'}
						<WorktreeTab />
					{/if}
				</div>
			</div>
		{:else if mainTab === 'tracking'}
			<div class="overflow-auto h-full">
				<TrackingTab />
			</div>
		{:else if mainTab === 'daily-report'}
			<div class="overflow-auto h-full">
				<DailyReportTab />
			</div>
		{/if}
	</div>
</TabbedPageLayout>
