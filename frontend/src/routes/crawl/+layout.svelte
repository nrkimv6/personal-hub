<script lang="ts">
	import type { Snippet } from 'svelte';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';

	let { children }: { children: Snippet } = $props();

	const crawlTabs = [
		{ id: 'history', label: '이력', href: '/crawl', exact: true },
		{ id: 'requests', label: '단건 요청', href: '/crawl/requests' },
		{ id: 'schedules', label: '스케줄', href: '/crawl/schedules' }
	];
</script>

<TabbedPageLayout
	title="크롤링"
	primaryTabs={crawlTabs}
	primaryUrlBased
	density="compact"
	containerClass="space-y-3 p-4 lg:p-6"
>
	{@render children()}
</TabbedPageLayout>
