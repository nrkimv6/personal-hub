<script lang="ts">
	import ProfileManager from '$lib/components/browsers/ProfileManager.svelte';
	import ProxyDashboard from '$lib/components/browsers/ProxyDashboard.svelte';
	import ProxyList from '$lib/components/browsers/ProxyList.svelte';
	import ProxyUsage from '$lib/components/browsers/ProxyUsage.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';

	type TabType = 'profiles' | 'proxy' | 'proxy-list' | 'usage';
	let activeTab: TabType = 'profiles';

	const tabs: { id: TabType; label: string }[] = [
		{ id: 'profiles', label: '프로필' },
		{ id: 'proxy', label: '프록시' },
		{ id: 'proxy-list', label: '프록시 목록' },
		{ id: 'usage', label: '사용 이력' }
	];
</script>

<div>

	<TabNav {tabs} bind:activeTab variant="secondary" />

	<!-- 탭 컨텐츠 -->
	{#if activeTab === 'profiles'}
		<ProfileManager />
	{:else if activeTab === 'proxy'}
		<ProxyDashboard />
	{:else if activeTab === 'proxy-list'}
		<ProxyList />
	{:else if activeTab === 'usage'}
		<ProxyUsage />
	{/if}
</div>
