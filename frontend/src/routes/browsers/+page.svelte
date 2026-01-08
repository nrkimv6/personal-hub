<script lang="ts">
	import { page } from '$app/stores';
	import ProfileManager from '$lib/components/browsers/ProfileManager.svelte';
	import ProxyDashboard from '$lib/components/browsers/ProxyDashboard.svelte';
	import ProxyList from '$lib/components/browsers/ProxyList.svelte';
	import ProxyUsage from '$lib/components/browsers/ProxyUsage.svelte';

	type TabType = 'profiles' | 'proxy' | 'proxy-list' | 'usage';
	let activeTab: TabType = 'profiles';

	// URL 파라미터에서 탭 초기화 (하위 호환성: accounts → profiles)
	$: {
		const tab = $page.url.searchParams.get('tab');
		if (tab === 'accounts' || tab === 'profiles') {
			activeTab = 'profiles';
		} else if (tab === 'proxy' || tab === 'proxy-list' || tab === 'usage') {
			activeTab = tab;
		}
	}

	const tabs: { id: TabType; label: string }[] = [
		{ id: 'profiles', label: '프로필' },
		{ id: 'proxy', label: '프록시' },
		{ id: 'proxy-list', label: '프록시 목록' },
		{ id: 'usage', label: '사용 이력' }
	];
</script>

<div class="p-6">
	<div class="mb-6">
		<h1 class="text-2xl font-bold text-foreground">브라우저 관리</h1>
		<p class="text-muted-foreground mt-1">브라우저 프로필 및 프록시 관리</p>
	</div>

	<!-- 탭 네비게이션 -->
	<div class="border-b border-border mb-6">
		<nav class="flex space-x-8">
			{#each tabs as tab}
				<button
					class="py-2 px-1 border-b-2 font-medium text-sm {activeTab === tab.id
						? 'border-blue-500 text-blue-600'
						: 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}"
					onclick={() => (activeTab = tab.id)}
				>
					{tab.label}
				</button>
			{/each}
		</nav>
	</div>

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
