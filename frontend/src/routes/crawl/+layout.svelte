<script lang="ts">
	import TabNav from '$lib/components/layout/TabNav.svelte';

	const navTabs = [
		{ id: 'requests', label: '단건 요청', href: '/crawl/requests' },
		{ id: 'schedules', label: '스케줄', href: '/crawl/schedules' }
	];
</script>

<div class="min-h-screen bg-background">
	<!-- 서브 네비게이션 -->
	<div class="bg-white shadow-sm border-b border-border">
		<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
			<TabNav tabs={navTabs} variant="primary" urlBased size="compact" />
		</div>
	</div>

	<!-- 콘텐츠 -->
	<slot />
</div>
