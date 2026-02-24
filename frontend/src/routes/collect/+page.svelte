<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import CollectTab from './CollectTab.svelte';
	import VideoDownloadsTab from './VideoDownloadsTab.svelte';

	type MainTab = 'posts' | 'videos';
	let mainTab: MainTab = $state('posts');

	const mainTabs = [
		{ id: 'posts', label: '📥 포스트 수집' },
		{ id: 'videos', label: '🎬 비디오 다운로드' }
	];

	// URL 파라미터에서 탭 읽기
	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'videos') {
			mainTab = tabParam;
		} else {
			mainTab = 'posts';
		}
	});
</script>

<svelte:head>
	<title>수집 관리 | Monitor Page</title>
</svelte:head>

<div class="space-y-4">
	<PageHeader title="수집 관리" subtitle="포스트 수집과 비디오 다운로드를 관리합니다" />

	<TabNav tabs={mainTabs} bind:activeTab={mainTab} variant="primary" queryParam="tab" />

	{#if mainTab === 'posts'}
		<CollectTab />
	{:else if mainTab === 'videos'}
		<VideoDownloadsTab />
	{/if}
</div>
