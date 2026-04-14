<script lang="ts">
	import NotificationSettings from '$lib/components/NotificationSettings.svelte';
	import SchedulerSettings from '$lib/components/SchedulerSettings.svelte';
	import AiDefaultsSettings from '$lib/components/system/AiDefaultsSettings.svelte';
	import AiProfilesSettings from '$lib/components/system/AiProfilesSettings.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';

	type Tab = 'notification' | 'scheduler' | 'ai-defaults' | 'ai-profiles';
	let activeTab: Tab = 'notification';

	const settingsTabs: { id: Tab; label: string }[] = [
		{ id: 'notification', label: '알림' },
		{ id: 'scheduler', label: '스케줄러' },
		{ id: 'ai-defaults', label: 'AI 기본값' },
		{ id: 'ai-profiles', label: 'AI 프로필' },
	];
</script>

<div>

	<TabNav tabs={settingsTabs} bind:activeTab variant="secondary" />

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
