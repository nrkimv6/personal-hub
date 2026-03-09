<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerMergeApi, devRunnerLogApi } from '$lib/api/dev-runner';

	type MergeStatus = 'Queued' | 'Merging' | 'Testing' | 'Fixing' | 'Completed' | 'Failed';

	interface MergeItem {
		runner_id: string;
		status: string;
	}

	let waitItems: MergeItem[] = $state([]);
	let loading = $state(false);
	let error = $state('');
	let selectedRunnerId = $state<string | null>(null);
	let mergeLogLines = $state<string[]>([]);
	let mergeEventSource: EventSource | null = null;
	let pollInterval: ReturnType<typeof setInterval>;

	const STATUS_COLORS: Record<string, string> = {
		Queued:    'bg-yellow-100 text-yellow-800',
		Merging:   'bg-purple-100 text-purple-800',
		Testing:   'bg-cyan-100 text-cyan-800',
		Fixing:    'bg-orange-100 text-orange-800',
		Completed: 'bg-green-100 text-green-800',
		Failed:    'bg-red-100 text-red-800',
	};

	function statusColor(status: string): string {
		return STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-700';
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const raw = await devRunnerMergeApi.queue();
			waitItems = raw as unknown as MergeItem[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '불러오기 실패';
		} finally {
			loading = false;
		}
	}

	function selectRunner(runnerId: string) {
		if (selectedRunnerId === runnerId) {
			selectedRunnerId = null;
			closeMergeStream();
			return;
		}
		selectedRunnerId = runnerId;
		mergeLogLines = [];
		closeMergeStream();
		mergeEventSource = devRunnerLogApi.connectMergeStream(runnerId);
		mergeEventSource.onmessage = (e) => {
			mergeLogLines = [...mergeLogLines, e.data].slice(-200);
		};
	}

	function closeMergeStream() {
		mergeEventSource?.close();
		mergeEventSource = null;
	}

	onMount(() => {
		load();
		pollInterval = setInterval(load, 5000);
	});

	onDestroy(() => {
		clearInterval(pollInterval);
		closeMergeStream();
	});
</script>

<div class="p-4 flex flex-col h-full overflow-hidden">
	<div class="mb-3 flex items-center justify-between shrink-0">
		<div class="flex items-center gap-2">
			<h3 class="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Merge Queue</h3>
			{#if waitItems.length > 0}
				<span class="flex h-2 w-2 rounded-full bg-purple-500 animate-pulse"></span>
			{/if}
		</div>
		<button
			onclick={load}
			class="p-1 rounded-md hover:bg-gray-100 text-gray-400 transition-colors disabled:opacity-50"
			disabled={loading}
			title="Refresh"
		>
			<svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5 {loading ? 'animate-spin' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
		</button>
	</div>

	{#if error}
		<div class="bg-red-50 border border-red-100 text-red-600 text-[10px] p-2 rounded mb-3 shrink-0">{error}</div>
	{/if}

	<div class="flex-1 min-h-0 overflow-y-auto pr-0.5 custom-scrollbar">
		{#if waitItems.length === 0 && !loading}
			<div class="flex flex-col items-center justify-center py-10 text-gray-400">
				<svg xmlns="http://www.w3.org/2000/svg" class="w-8 h-8 mb-2 opacity-20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6 21V9a9 9 0 0 0 9 9"/><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/></svg>
				<p class="text-[11px] italic">No pending merge tasks</p>
			</div>
		{:else}
			<div class="space-y-2.5 pb-2">
				{#each waitItems as item (item.runner_id)}
					<div class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col transition-all hover:shadow-md">
						<!-- 헤더 행 (클릭 가능) -->
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<div
							class="flex items-center justify-between gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors"
							onclick={() => selectRunner(item.runner_id)}
							role="button"
							tabindex="0"
						>
							<div class="flex flex-col min-w-0">
								<span class="text-[10px] font-mono text-gray-400 truncate mb-0.5">{item.runner_id.slice(0, 12)}...</span>
								<p class="truncate text-[11px] font-bold text-gray-700">{item.runner_id}</p>
							</div>
							<span class="rounded-full px-2 py-0.5 text-[9px] font-bold uppercase {statusColor(item.status)}">
								{item.status}
							</span>
						</div>

						<!-- Failed 시 액션 버튼 (별도 행) -->
						{#if item.status === 'Failed'}
							<div class="flex items-center gap-2 px-3 pb-3 pt-1 border-t border-gray-50 bg-red-50/30">
								<button
									disabled
									class="flex-1 px-2 py-1 text-[10px] font-bold rounded-md bg-white border border-gray-200 text-gray-400 opacity-50 cursor-not-allowed transition-colors"
								>RETRY</button>
								<button
									disabled
									class="flex-1 px-2 py-1 text-[10px] font-bold rounded-md bg-white border border-red-100 text-red-400 opacity-50 cursor-not-allowed transition-colors"
								>REVERT</button>
							</div>
						{/if}

						<!-- 로그 영역 (선택 시) -->
						{#if selectedRunnerId === item.runner_id}
							<div class="max-h-[200px] overflow-y-auto bg-gray-900 font-mono text-[10px] p-3 border-t border-gray-200" role="log">
								{#if mergeLogLines.length === 0}
									<div class="flex items-center justify-center py-6 gap-2 text-gray-500">
										<svg class="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-dashoffset="10"/></svg>
										<span>Connecting to merge stream...</span>
									</div>
								{:else}
									<div class="space-y-1">
										{#each mergeLogLines as line}
											<div class="text-gray-300 leading-normal break-words">{line}</div>
										{/each}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
