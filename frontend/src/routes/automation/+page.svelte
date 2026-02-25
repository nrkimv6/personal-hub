<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import DevRunnerTab from './DevRunnerTab.svelte';
	import SleepNowTab from './SleepNowTab.svelte';
	import GitReposTab from './GitReposTab.svelte';
	import PlanListTab from '../plans/PlanListTab.svelte';
	import ArchiveTab from '../plans/ArchiveTab.svelte';
	import HistoryTab from '../plans/HistoryTab.svelte';

	type MainTab = 'dev-runner' | 'sleep-now' | 'git-repos' | 'plans';
	let mainTab: MainTab = $state('dev-runner');
	let initialPlan = $state('');

	// plans 서브탭
	type PlansSubTab = 'plans' | 'archive' | 'history';
	let plansSubTab: PlansSubTab = $state('plans');

	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'sleep-now') {
			mainTab = 'sleep-now';
		} else if (tabParam === 'git-repos') {
			mainTab = 'git-repos';
		} else if (tabParam === 'plans') {
			mainTab = 'plans';
			const subParam = $page.url.searchParams.get('subtab') as PlansSubTab | null;
			plansSubTab = subParam && ['plans', 'archive', 'history'].includes(subParam) ? subParam : 'plans';
		} else {
			mainTab = 'dev-runner';
		}
		initialPlan = $page.url.searchParams.get('plan') ?? '';
	});

	function setPlansSubTab(sub: PlansSubTab) {
		const url = new URL($page.url);
		url.searchParams.set('tab', 'plans');
		if (sub === 'plans') {
			url.searchParams.delete('subtab');
		} else {
			url.searchParams.set('subtab', sub);
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	}

	const autoTabs = [
		{ id: 'dev-runner', label: '🚀 Dev Runner' },
		{ id: 'sleep-now', label: 'Sleep Now' },
		{ id: 'git-repos', label: '📂 Git 관리' },
		{ id: 'plans', label: '📋 계획서' },
	];

	function setMainTab(tab: MainTab) {
		const url = new URL($page.url);
		if (tab === 'dev-runner') {
			url.searchParams.delete('tab');
			url.searchParams.delete('subtab');
		} else {
			url.searchParams.set('tab', tab);
			if (tab !== 'plans') url.searchParams.delete('subtab');
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	}
</script>

<svelte:head>
	<title>{mainTab === 'git-repos' ? 'Git 관리' : mainTab === 'plans' ? '계획서 관리' : '시스템 자동화'} | Monitor Page</title>
</svelte:head>

<div class="flex flex-col h-full overflow-hidden">
	<div class="flex items-center gap-4 px-4 lg:px-6 h-12 border-b shrink-0">
		<h1 class="text-base font-bold tracking-tight text-foreground">시스템 자동화</h1>
		<TabNav tabs={autoTabs} bind:activeTab={mainTab} variant="primary" size="compact" queryParam="tab" />
	</div>

	<div class="flex-1 overflow-hidden">
		{#if mainTab === 'dev-runner'}
			<DevRunnerTab {initialPlan} />
		{:else if mainTab === 'sleep-now'}
			<div class="p-6 overflow-auto h-full">
				<SleepNowTab />
			</div>
		{:else if mainTab === 'git-repos'}
			<div class="overflow-auto h-full">
				<GitReposTab />
			</div>
		{:else if mainTab === 'plans'}
			<div class="flex flex-col h-full overflow-hidden">
				<!-- 계획서 서브탭 -->
				<div class="flex gap-1 px-4 pt-3 pb-2 border-b border-border shrink-0">
					<button
						onclick={() => setPlansSubTab('plans')}
						class="px-3 py-1 text-xs font-medium rounded transition-colors {plansSubTab === 'plans'
							? 'bg-primary/10 text-primary'
							: 'text-muted-foreground hover:bg-muted/40'}"
					>
						계획
					</button>
					<button
						onclick={() => setPlansSubTab('archive')}
						class="px-3 py-1 text-xs font-medium rounded transition-colors {plansSubTab === 'archive'
							? 'bg-primary/10 text-primary'
							: 'text-muted-foreground hover:bg-muted/40'}"
					>
						아카이브
					</button>
					<button
						onclick={() => setPlansSubTab('history')}
						class="px-3 py-1 text-xs font-medium rounded transition-colors {plansSubTab === 'history'
							? 'bg-primary/10 text-primary'
							: 'text-muted-foreground hover:bg-muted/40'}"
					>
						이력
					</button>
				</div>
				<div class="flex-1 overflow-auto p-4">
					{#if plansSubTab === 'plans'}
						<PlanListTab />
					{:else if plansSubTab === 'archive'}
						<ArchiveTab />
					{:else if plansSubTab === 'history'}
						<HistoryTab />
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
