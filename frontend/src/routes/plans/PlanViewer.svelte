<script lang="ts">
	import { onMount } from 'svelte';
	import { devRunnerPlanApi } from '$lib/api/dev-runner';
	import { renderMarkdown } from '../notes/utils/markdown';
	import 'highlight.js/styles/github.css';

	interface Props {
		filePath: string;
	}

	let { filePath }: Props = $props();

	let html = $state('');
	let loading = $state(false);
	let error = $state('');

	async function loadContent(path: string) {
		if (!path) return;
		loading = true;
		error = '';
		html = '';
		try {
			const encoded = btoa(unescape(encodeURIComponent(path)));
			const res = await devRunnerPlanApi.content(encoded);
			html = renderMarkdown(res.content);
		} catch (e: any) {
			error = e?.message ?? '내용을 불러오지 못했습니다.';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		loadContent(filePath);
	});

	$effect(() => {
		loadContent(filePath);
	});
</script>

{#if loading}
	<div class="flex items-center justify-center py-8 text-gray-400 text-sm">
		<svg class="animate-spin h-5 w-5 mr-2 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
			<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
			<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
		</svg>
		불러오는 중...
	</div>
{:else if error}
	<div class="text-red-500 text-sm py-4 px-2">
		{error}
	</div>
{:else}
	<div class="prose prose-sm overflow-auto max-h-[60vh] px-1">{@html html}</div>
{/if}
