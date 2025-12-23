<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import InstagramCrawlSettings from '$lib/components/InstagramCrawlSettings.svelte';
	import InstagramCrawlHistory from '$lib/components/InstagramCrawlHistory.svelte';

	type Tab = 'settings' | 'history';
	let activeTab: Tab = 'settings';

	// URL 쿼리에서 탭 읽기
	$: {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'history') {
			activeTab = 'history';
		} else {
			activeTab = 'settings';
		}
	}

	function switchTab(tab: Tab) {
		activeTab = tab;
		const url = new URL(window.location.href);
		if (tab === 'settings') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.pathname + url.search, { replaceState: true, keepFocus: true });
	}
</script>

<div class="p-6">
	<div class="mb-6">
		<h2 class="text-2xl font-bold text-gray-900">수집 관리</h2>
		<p class="text-sm text-gray-500 mt-1">Instagram 피드 수집 설정 및 이력</p>
	</div>

	<!-- 탭 -->
	<div class="mb-6 border-b border-gray-200">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('settings')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'settings'
					? 'border-blue-600 text-blue-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				설정
			</button>
			<button
				onclick={() => switchTab('history')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'history'
					? 'border-blue-600 text-blue-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				이력
			</button>
		</nav>
	</div>

	{#if activeTab === 'settings'}
		<InstagramCrawlSettings />
	{:else if activeTab === 'history'}
		<InstagramCrawlHistory />
	{/if}
</div>
