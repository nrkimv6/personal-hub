<script>
	import MobileServerStatus from '$lib/components/MobileServerStatus.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';

	const navTabs = [
		{ id: 'targets', label: '크롤링 대상', href: '/mobile/targets' },
		{ id: 'items', label: '수집 아이템', href: '/mobile/items' },
		{ id: 'history', label: '실행 이력', href: '/mobile/history' },
		{ id: 'fetch', label: 'HTML 수집 도구', href: '/mobile/fetch' },
		{ id: 'analyze', label: 'HTML 분석 도구', href: '/mobile/analyze' }
	];
</script>

<div class="mb-4 border-b pb-4">
	<div class="flex justify-between items-center mb-4">
		<h1 class="text-3xl font-bold">모바일 크롤링</h1>
		<MobileServerStatus />
	</div>

	<TabNav tabs={navTabs} variant="primary" urlBased />
</div>

<slot />
