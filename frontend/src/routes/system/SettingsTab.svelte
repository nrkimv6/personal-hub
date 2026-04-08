<script lang="ts">
	import NotificationSettings from '$lib/components/NotificationSettings.svelte';
	import SchedulerSettings from '$lib/components/SchedulerSettings.svelte';
	import AiDefaultsSettings from '$lib/components/system/AiDefaultsSettings.svelte';
	import AiProfilesSettings from '$lib/components/system/AiProfilesSettings.svelte';

	type Tab = 'notification' | 'scheduler' | 'ai-defaults' | 'ai-profiles';
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
			<button
				onclick={() => switchTab('ai-defaults')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab ===
				'ai-defaults'
					? 'border-blue-600 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				AI 기본값
			</button>
			<button
				onclick={() => switchTab('ai-profiles')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab ===
				'ai-profiles'
					? 'border-blue-600 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				AI 프로필
			</button>
		</nav>
	</div>

	{#if activeTab === 'notification'}
		<NotificationSettings />
	{:else if activeTab === 'scheduler'}
		<SchedulerSettings />
	{:else if activeTab === 'ai-defaults'}
		<AiDefaultsSettings />
	{:else if activeTab === 'ai-profiles'}
		<AiProfilesSettings />
	{/if}
</div>
