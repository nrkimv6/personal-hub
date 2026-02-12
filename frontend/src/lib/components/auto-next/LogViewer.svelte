<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { autoNextLogApi } from '$lib/api';

	interface LogLine {
		text: string;
		isStale: boolean;
	}

	let lines = $state<LogLine[]>([]);
	let connected = $state(false);
	let autoScroll = $state(true);
	let logContainer: HTMLDivElement;
	let eventSource: EventSource | null = null;
	let sseStarted = $state(false);

	const MAX_LINES = 500;
	const SEPARATOR_PATTERN = '════════════════';

	function addLine(text: string, isStale: boolean) {
		// 구분자 감지 시 이전 라인을 모두 stale로 전환
		if (text.includes(SEPARATOR_PATTERN) && !isStale) {
			lines = lines.map((l) => ({ ...l, isStale: true }));
		}

		lines.push({ text, isStale });
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
			sseStarted = true;
		};
		eventSource.onmessage = (event) => {
			addLine(event.data, false);
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
			// 초기 로드된 라인은 모두 stale (이전 로그)
			lines = res.lines.map((text: string) => ({ text, isStale: true }));
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
				<div
					class="whitespace-pre-wrap break-all {line.isStale ? 'opacity-40 text-gray-500' : ''}"
				>
					{line.text}
				</div>
			{/each}
		{/if}
	</div>
</div>
