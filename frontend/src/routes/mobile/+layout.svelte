<script>
	import MobileServerStatus from '$lib/components/MobileServerStatus.svelte';
	import { page } from '$app/stores';

	const navItems = [
		{ path: '/mobile/targets', label: '크롤링 대상' },
		{ path: '/mobile/items', label: '수집 아이템' },
		{ path: '/mobile/history', label: '실행 이력' },
		{ path: '/mobile/fetch', label: 'HTML 수집 도구' },
		{ path: '/mobile/analyze', label: 'HTML 분석 도구' }
	];
</script>

<div class="mb-4 border-b pb-4">
	<div class="flex justify-between items-center mb-4">
		<h1 class="text-3xl font-bold">모바일 크롤링</h1>
		<MobileServerStatus />
	</div>

	<div class="tabs tabs-boxed overflow-x-auto flex-nowrap whitespace-nowrap">
		{#each navItems as item}
			<a
				href={item.path}
				class="tab"
				class:tab-active={$page.url.pathname === item.path || $page.url.pathname.startsWith(item.path + '/')}
			>
				{item.label}
			</a>
		{/each}
	</div>
</div>

<slot />
