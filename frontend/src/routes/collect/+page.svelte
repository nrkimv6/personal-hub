<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import CollectTab from './CollectTab.svelte';
	import VideoDownloadsTab from './VideoDownloadsTab.svelte';

	type MainTab = 'posts' | 'videos';
	let mainTab: MainTab = $state('posts');

	// URL 파라미터에서 탭 읽기
	$effect(() => {
		const tabParam = $page.url.searchParams.get('tab');
		if (tabParam === 'videos') {
			mainTab = tabParam;
		} else {
			mainTab = 'posts';
		}
	});

	function setMainTab(tab: MainTab) {
		const url = new URL($page.url);
		if (tab === 'posts') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	}
</script>

<svelte:head>
	<title>수집 관리 | Monitor Page</title>
</svelte:head>

<div class="p-6">
	<h1 class="text-2xl font-bold text-foreground mb-4">수집 관리</h1>

	<!-- 최상위 탭 -->
	<div class="mb-6 border-b border-border">
		<nav class="flex gap-4">
			<button
				onclick={() => setMainTab('posts')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {mainTab === 'posts'
					? 'border-blue-500 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				📥 포스트 수집
			</button>
			<button
				onclick={() => setMainTab('videos')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {mainTab === 'videos'
					? 'border-blue-500 text-primary'
					: 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				🎬 비디오 다운로드
			</button>
		</nav>
	</div>

	{#if mainTab === 'posts'}
		<CollectTab />
	{:else if mainTab === 'videos'}
		<VideoDownloadsTab />
	{/if}
</div>
