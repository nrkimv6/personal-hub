<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { autoNextLogApi } from '$lib/api';

	let lines = $state<string[]>([]);
	let connected = $state(false);
	let autoScroll = $state(true);
	let logContainer: HTMLDivElement;
	let eventSource: EventSource | null = null;

	const MAX_LINES = 500;

	function addLine(line: string) {
		lines.push(line);
		if (lines.length > MAX_LINES) {
			lines = lines.slice(lines.length - MAX_LINES);
		}
		if (autoScroll && logContainer) {
			requestAnimationFrame(() => {
				logContainer.scrollTop = logContainer.scrollHeight;
			});
		}
	}

	function connectSSE() {
		if (eventSource) eventSource.close();

		eventSource = autoNextLogApi.connectStream();
		eventSource.onopen = () => {
			connected = true;
		};
		eventSource.onmessage = (event) => {
			addLine(event.data);
		};
		eventSource.onerror = () => {
			connected = false;
			eventSource?.close();
			eventSource = null;
			// 5초 후 재연결
			setTimeout(connectSSE, 5000);
		};
	}

	async function loadRecent() {
		try {
			const res = await autoNextLogApi.recent(100);
			lines = res.lines;
		} catch {
			// 로그 없을 수 있음
		}
	}

	onMount(async () => {
		await loadRecent();
		connectSSE();
	});

	onDestroy(() => {
		if (eventSource) {
			eventSource.close();
			eventSource = null;
		}
	});
</script>

<div class="bg-white rounded-lg border">
	<div class="p-4 border-b flex items-center justify-between">
		<div class="flex items-center gap-2">
			<h2 class="font-semibold">로그</h2>
			{#if connected}
				<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">
					<span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
					연결됨
				</span>
			{:else}
				<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">
					<span class="w-1.5 h-1.5 rounded-full bg-gray-400"></span>
					끊김
				</span>
			{/if}
		</div>
		<label class="flex items-center gap-1.5 text-xs text-gray-500">
			<input type="checkbox" bind:checked={autoScroll} />
			자동 스크롤
		</label>
	</div>
	<div
		bind:this={logContainer}
		class="h-64 overflow-auto bg-gray-900 text-gray-200 text-xs font-mono p-3 leading-5"
	>
		{#if lines.length === 0}
			<span class="text-gray-500">로그가 없습니다</span>
		{:else}
			{#each lines as line}
				<div class="whitespace-pre-wrap break-all">{line}</div>
			{/each}
		{/if}
	</div>
</div>
