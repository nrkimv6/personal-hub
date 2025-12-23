<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import NotificationSettings from '$lib/components/NotificationSettings.svelte';
	import SchedulerSettings from '$lib/components/SchedulerSettings.svelte';

	type Tab = 'notification' | 'scheduler';
	let activeTab: Tab = 'notification';

	// URL 쿼리에서 탭 읽기
	$: {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'scheduler') {
			activeTab = 'scheduler';
		} else {
			activeTab = 'notification';
		}
	}

	function switchTab(tab: Tab) {
		activeTab = tab;
		const url = new URL(window.location.href);
		if (tab === 'notification') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.pathname + url.search, { replaceState: true, keepFocus: true });
	}
</script>

<div class="p-6">
	<div class="mb-6">
		<h2 class="text-2xl font-bold text-gray-900">설정</h2>
	</div>

	<!-- 탭 -->
	<div class="mb-6 border-b border-gray-200">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('notification')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab ===
				'notification'
					? 'border-blue-600 text-blue-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				알림
			</button>
			<button
				onclick={() => switchTab('scheduler')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab ===
				'scheduler'
					? 'border-blue-600 text-blue-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				스케줄러
			</button>
		</nav>
	</div>

	{#if activeTab === 'notification'}
		<NotificationSettings />
	{:else if activeTab === 'scheduler'}
		<SchedulerSettings />
	{/if}
</div>
