<script lang="ts">
	import { page } from '$app/stores';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import DevRunnerTab from './DevRunnerTab.svelte';
	import GitReposTab from './GitReposTab.svelte';
	import PlanListTab from '../plans/PlanListTab.svelte';
	import ArchiveTab from '../plans/ArchiveTab.svelte';
	import HistoryTab from '../plans/HistoryTab.svelte';
	import WorktreeTab from '../plans/WorktreeTab.svelte';

	type MainTab = 'dev-runner' | 'git-repos' | 'plans';
	let mainTab = $state<MainTab>('dev-runner');
	let initialPlan = $state('');
	let initialRunner = $state('');

	// plans 서브탭
	type PlansSubTab = 'plans' | 'archive' | 'history' | 'worktrees';
	let plansSubTab: PlansSubTab = $state('plans');

	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		const subParam = $page.url.searchParams.get('subtab') as PlansSubTab | null;
		const hasValidPlansSubtab = !!(subParam && ['plans', 'archive', 'history', 'worktrees'].includes(subParam));
		if (tabParam === 'git-repos') {
			mainTab = 'git-repos';
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
	];

	const plansSubTabs = [
		{ id: 'plans', label: '계획' },
		{ id: 'archive', label: '아카이브' },
		{ id: 'history', label: '이력' },
		{ id: 'worktrees', label: '워크트리' },
	];

	const pageTitle = $derived(
		mainTab === 'git-repos' ? 'Git 관리' : mainTab === 'plans' ? '계획서 관리' : '개발 파이프라인'
	);
</script>

<svelte:head>
	<title>{mainTab === 'git-repos' ? 'Git 관리' : mainTab === 'plans' ? '계획서 관리' : '개발 파이프라인'} | Monitor Page</title>
</svelte:head>

<div class="flex flex-col h-full overflow-hidden">
	<div class="p-4 lg:p-6 space-y-4">
		<PageHeader title={pageTitle} />
		<TabNav tabs={autoTabs} bind:activeTab={mainTab} variant="primary" queryParam="tab" />
	</div>

	<div class="flex-1 overflow-hidden">
		{#if mainTab === 'dev-runner'}
			<DevRunnerTab {initialPlan} {initialRunner} />
		{:else if mainTab === 'git-repos'}
			<div class="overflow-auto h-full">
				<GitReposTab />
			</div>
		{:else if mainTab === 'plans'}
			<div class="space-y-4 flex flex-col h-full overflow-hidden">
				<!-- 계획서 서브탭 -->
				<TabNav tabs={plansSubTabs} bind:activeTab={plansSubTab} variant="secondary" size="compact" queryParam="subtab" />
				<div class="flex-1 overflow-auto">
					{#if plansSubTab === 'plans'}
						<PlanListTab />
					{:else if plansSubTab === 'archive'}
						<ArchiveTab />
					{:else if plansSubTab === 'history'}
						<HistoryTab />
					{:else if plansSubTab === 'worktrees'}
						<WorktreeTab />
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
