<script lang="ts">
	import { page } from '$app/stores';
	import AccountManager from '$lib/components/browsers/AccountManager.svelte';
	import ProxyDashboard from '$lib/components/browsers/ProxyDashboard.svelte';
	import ProxyList from '$lib/components/browsers/ProxyList.svelte';
	import ProxyUsage from '$lib/components/browsers/ProxyUsage.svelte';

	type TabType = 'accounts' | 'proxy' | 'proxy-list' | 'usage';
	let activeTab: TabType = 'accounts';

	// URL 파라미터에서 탭 초기화
	$: {
		const tab = $page.url.searchParams.get('tab');
		if (tab === 'accounts' || tab === 'proxy' || tab === 'proxy-list' || tab === 'usage') {
			activeTab = tab;
		}
	}

	const tabs: { id: TabType; label: string }[] = [
		{ id: 'accounts', label: '계정' },
		{ id: 'proxy', label: '프록시' },
		{ id: 'proxy-list', label: '프록시 목록' },
		{ id: 'usage', label: '사용 이력' }
	];
</script>

<div class="p-6">
	<div class="mb-6">
		<h1 class="text-2xl font-bold text-gray-900">브라우저 관리</h1>
		<p class="text-gray-500 mt-1">브라우저 계정 및 프록시 관리</p>
	</div>

	<!-- 탭 네비게이션 -->
	<div class="border-b border-gray-200 mb-6">
		<nav class="flex space-x-8">
			{#each tabs as tab}
				<button
					class="py-2 px-1 border-b-2 font-medium text-sm {activeTab === tab.id
						? 'border-blue-500 text-blue-600'
						: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
					onclick={() => (activeTab = tab.id)}
				>
					{tab.label}
				</button>
			{/each}
		</nav>
	</div>

	<!-- 탭 컨텐츠 -->
	{#if activeTab === 'accounts'}
		<AccountManager />
	{:else if activeTab === 'proxy'}
		<ProxyDashboard />
	{:else if activeTab === 'proxy-list'}
		<ProxyList />
	{:else if activeTab === 'usage'}
		<ProxyUsage />
	{/if}
</div>
