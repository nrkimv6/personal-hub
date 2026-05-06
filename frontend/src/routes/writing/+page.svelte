<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import WritingTab from './WritingTab.svelte';
	import ReportsTab from './ReportsTab.svelte';

	type MainTab = 'writings' | 'reports';
	let mainTab: MainTab = $state('writings');

	const writingTabs = [
		{ id: 'writings', label: '글쓰기' },
		{ id: 'reports', label: '보고서' }
	];

	// URL 파라미터에서 탭 읽기 (?tab=llm 은 /llm으로 리다이렉트, 하위호환)
	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'llm') {
			goto('/llm', { replaceState: true });
		} else if (tabParam === 'reports') {
			mainTab = 'reports';
		} else {
			mainTab = 'writings';
		}
	});
</script>

<svelte:head>
	<title>AI / 글쓰기 | Monitor Page</title>
</svelte:head>

<div class="p-4 lg:p-6 space-y-4">
	<PageHeader title="AI / 글쓰기" />

	<TabNav tabs={writingTabs} bind:activeTab={mainTab} variant="primary" queryParam="tab" />

	{#if mainTab === 'writings'}
		<WritingTab />
	{:else if mainTab === 'reports'}
		<ReportsTab />
	{/if}
</div>
