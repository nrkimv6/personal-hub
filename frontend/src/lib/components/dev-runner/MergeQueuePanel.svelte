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

<div class="p-3">
	<div class="mb-2 flex items-center justify-between">
		<h3 class="text-xs font-semibold text-gray-600 uppercase tracking-wide">Merge 대기 큐</h3>
		<button
			onclick={load}
			class="rounded px-2 py-0.5 text-xs text-gray-400 hover:bg-gray-100 disabled:opacity-50"
			disabled={loading}
		>
			{loading ? '...' : '새로고침'}
		</button>
	</div>

	{#if error}
		<p class="text-xs text-red-500 mb-2">{error}</p>
	{/if}

	{#if waitItems.length === 0 && !loading}
		<p class="text-center text-xs text-gray-400 py-4">merge lock 대기 중인 runner 없음</p>
	{:else}
		<div class="space-y-1.5">
			{#each waitItems as item (item.runner_id)}
				<div class="rounded border border-gray-100 bg-gray-50 overflow-hidden">
					<!-- 헤더 행 (클릭 가능) -->
					<div
						class="flex items-center justify-between gap-2 px-2.5 py-1.5 cursor-pointer hover:bg-gray-100 transition-colors"
						onclick={() => selectRunner(item.runner_id)}
						role="button"
						tabindex="0"
						onkeydown={(e) => e.key === 'Enter' && selectRunner(item.runner_id)}
					>
						<p class="truncate text-xs font-mono text-gray-800 flex-1 min-w-0">{item.runner_id}</p>
						<div class="flex items-center gap-1 shrink-0">
							<span class="rounded px-1.5 py-0.5 text-[10px] font-medium {statusColor(item.status)}">
								{item.status}
							</span>
						</div>
					</div>

					<!-- Failed 시 액션 버튼 (별도 행) -->
					{#if item.status === 'Failed'}
						<div class="flex items-center gap-1 px-2.5 pb-1.5">
							<span class="text-[10px] text-gray-400 mr-1">Actions:</span>
							<button
								disabled
								class="px-2 py-0.5 text-[10px] rounded border border-gray-200 text-gray-400 opacity-50 cursor-not-allowed"
								title="기능 준비 중"
							>↺ Retry</button>
							<button
								disabled
								class="px-2 py-0.5 text-[10px] rounded border border-red-200 text-red-400 opacity-50 cursor-not-allowed"
								title="기능 준비 중"
							>↩ Revert</button>
						</div>
					{/if}

					<!-- 로그 영역 (선택 시) -->
					{#if selectedRunnerId === item.runner_id}
						<div class="max-h-[180px] overflow-y-auto bg-gray-950 font-mono text-xs p-2" role="log">
							{#if mergeLogLines.length === 0}
								<p class="text-gray-500 text-center py-2">Waiting...</p>
							{:else}
								{#each mergeLogLines as line}
									<div class="text-gray-300 leading-5">{line}</div>
								{/each}
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
