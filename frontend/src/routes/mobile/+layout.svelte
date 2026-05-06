<script lang="ts">
	import type { Snippet } from 'svelte';
	import MobileServerStatus from '$lib/components/MobileServerStatus.svelte';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';

	let { children: pageContent }: { children: Snippet } = $props();

	const navTabs = [
		{ id: 'targets', label: '크롤링 대상', href: '/mobile/targets' },
		{ id: 'items', label: '수집 아이템', href: '/mobile/items' },
		{ id: 'history', label: '실행 이력', href: '/mobile/history' },
		{ id: 'fetch', label: 'HTML 수집 도구', shortLabel: '수집 도구', href: '/mobile/fetch' },
		{ id: 'analyze', label: 'HTML 분석 도구', shortLabel: '분석 도구', href: '/mobile/analyze' }
	];
</script>

{#snippet headerActions()}
	<MobileServerStatus />
{/snippet}

<TabbedPageLayout
	title="모바일 크롤링"
	actions={headerActions}
	primaryTabs={navTabs}
	primaryUrlBased
	density="compact"
	containerClass="space-y-3 p-4 lg:p-6"
>
	{@render pageContent()}
</TabbedPageLayout>
