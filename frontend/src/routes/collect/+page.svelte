<script lang="ts">
	import { page } from '$app/stores';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import CollectTab from './CollectTab.svelte';
	import VideoDownloadsTab from './VideoDownloadsTab.svelte';

	type MainTab = 'posts' | 'videos';
	let mainTab: MainTab = $state('posts');

	const mainTabs = [
		{ id: 'posts', label: '포스트 수집' },
		{ id: 'videos', label: '비디오 다운로드' }
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

<TabbedPageLayout
	secondaryTabs={mainTabs}
	bind:activeSecondaryTab={mainTab}
	secondaryQueryParam="tab"
	containerClass="space-y-3"
	contentClass="min-w-0"
>
	{#if mainTab === 'posts'}
		<CollectTab />
	{:else if mainTab === 'videos'}
		<VideoDownloadsTab />
	{/if}
</TabbedPageLayout>
