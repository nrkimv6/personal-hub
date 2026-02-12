<script lang="ts">
	import NotificationSettings from '$lib/components/NotificationSettings.svelte';
	import SchedulerSettings from '$lib/components/SchedulerSettings.svelte';

	type Tab = 'notification' | 'scheduler';
	let activeTab: Tab = 'notification';

	function switchTab(tab: Tab) {
		activeTab = tab;
	}
</script>

<div>

	<!-- 탭 -->
	<div class="mb-6 border-b border-border">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('notification')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab ===
				'notification'
					? 'border-blue-600 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				알림
			</button>
			<button
				onclick={() => switchTab('scheduler')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab ===
				'scheduler'
					? 'border-blue-600 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
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
