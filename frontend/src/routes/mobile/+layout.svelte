<script lang="ts">
	import type { Snippet } from 'svelte';
	import MobileServerStatus from '$lib/components/MobileServerStatus.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';

	let { children: pageContent }: { children: Snippet } = $props();

	const navTabs = [
		{ id: 'targets', label: '크롤링 대상', href: '/mobile/targets' },
		{ id: 'items', label: '수집 아이템', href: '/mobile/items' },
		{ id: 'history', label: '실행 이력', href: '/mobile/history' },
		{ id: 'fetch', label: 'HTML 수집 도구', href: '/mobile/fetch' },
		{ id: 'analyze', label: 'HTML 분석 도구', href: '/mobile/analyze' }
	];
</script>

<div class="p-4 lg:p-6">
	<div class="mb-4 border-b pb-4">
		<PageHeader title="모바일 크롤링">
			{#snippet children()}<MobileServerStatus />{/snippet}
		</PageHeader>

		<TabNav tabs={navTabs} variant="primary" urlBased />
	</div>

	{@render pageContent()}
</div>
