<script lang="ts">
	import { devRunnerLogApi, type RunHistoryItem } from '$lib/api';

	interface Props {
		selectedRunnerId?: string | null;
		onSelect?: (item: RunHistoryItem) => void;
	}

	let { selectedRunnerId = $bindable(null), onSelect }: Props = $props();

	let runs = $state<RunHistoryItem[]>([]);
	let total = $state(0);
	let loading = $state(false);
	let error = $state<string | null>(null);
	const limit = 30;
	let offset = $state(0);

	async function loadHistory() {
		loading = true;
		error = null;
		try {
			const res = await devRunnerLogApi.history(limit, offset);
			runs = res.runs;
			total = res.total;
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	}

	function selectRunner(item: RunHistoryItem) {
		selectedRunnerId = item.runner_id;
		onSelect?.(item);
	}

	function formatTime(iso: string | null): string {
		if (!iso) return '—';
		try {
			return new Date(iso).toLocaleString('ko-KR', {
				month: '2-digit', day: '2-digit',
				hour: '2-digit', minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}

	function shortId(id: string): string {
		return id.slice(0, 8);
	}

	$effect(() => {
		loadHistory();
	});
</script>

<div class="flex flex-col h-full bg-gray-900 border-r border-gray-700 w-64 min-w-[220px]">
	<!-- 헤더 -->
	<div class="flex items-center justify-between px-3 py-2 border-b border-gray-700">
		<span class="text-xs font-semibold text-gray-300 uppercase tracking-wide">실행 이력</span>
		<button
			onclick={loadHistory}
			class="text-gray-500 hover:text-gray-300 transition-colors"
			title="새로고침"
		>
			<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
					d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
			</svg>
		</button>
	</div>

	<!-- 목록 -->
	<div class="flex-1 overflow-y-auto">
		{#if loading}
			<div class="p-4 text-center text-gray-500 text-xs">로딩 중…</div>
		{:else if error}
			<div class="p-3 text-red-400 text-xs">{error}</div>
		{:else if runs.length === 0}
			<div class="p-4 text-center text-muted-foreground text-xs">실행 이력 없음</div>
		{:else}
			{#each runs as item (item.runner_id)}
				<button
					onclick={() => selectRunner(item)}
					class="w-full text-left px-3 py-2.5 border-b border-gray-800 hover:bg-gray-800 transition-colors
						{selectedRunnerId === item.runner_id ? 'bg-gray-800 border-l-2 border-l-blue-500' : ''}"
				>
					<!-- runner_id + status -->
					<div class="flex items-center gap-1.5 mb-0.5">
						<span class="w-1.5 h-1.5 rounded-full flex-shrink-0
							{item.status === 'running' ? 'bg-green-400 animate-pulse' : 'bg-gray-500'}">
						</span>
						<span class="font-mono text-xs text-gray-300 truncate">{shortId(item.runner_id)}</span>
						{#if item.engine}
							<span class="ml-auto text-[10px] text-gray-500 flex-shrink-0">{item.engine}</span>
						{/if}
					</div>
					<!-- branch -->
					<div class="text-[10px] pl-3 truncate {item.branch ? 'text-blue-400' : 'text-muted-foreground'}">
						{item.branch ?? 'main'}
						{#if item.merge_status}
							<span class="ml-1 px-1 rounded text-[9px] {
								item.merge_status === 'merged' ? 'bg-green-900 text-green-300' :
								item.merge_status === 'approval_required' ? 'bg-yellow-900 text-yellow-300' :
								item.merge_status === 'pending' ? 'bg-yellow-900 text-yellow-300' :
								'bg-gray-700 text-gray-400'
							}">{item.merge_status}</span>
						{/if}
					</div>
					{#if item.plan_file}
						<div class="text-[10px] text-gray-500 truncate pl-3" title={item.plan_file}>
							{item.plan_file.split('/').pop() ?? item.plan_file}
						</div>
					{/if}
					<!-- time + pid + execution_count -->
					<div class="text-[10px] text-muted-foreground pl-3 mt-0.5 flex items-center gap-1.5">
						{formatTime(item.start_time)}
						{#if item.pid}
							<span class="ml-1">PID:{item.pid}</span>
						{/if}
						{#if item.execution_count != null}
							<span class="px-1 py-0.5 rounded bg-indigo-900/40 text-indigo-300">{item.execution_count}번째</span>
						{/if}
					</div>
				</button>
			{/each}
		{/if}
	</div>

	<!-- 페이지네이션 (total > limit일 때) -->
	{#if total > limit}
		<div class="flex items-center justify-between px-3 py-1.5 border-t border-gray-700 text-[10px] text-gray-500">
			<span>{offset + 1}–{Math.min(offset + limit, total)} / {total}</span>
			<div class="flex gap-1">
				<button
					disabled={offset === 0}
					onclick={() => { offset = Math.max(0, offset - limit); loadHistory(); }}
					class="px-1.5 py-0.5 rounded bg-gray-800 disabled:opacity-40 hover:bg-gray-700"
				>◀</button>
				<button
					disabled={offset + limit >= total}
					onclick={() => { offset += limit; loadHistory(); }}
					class="px-1.5 py-0.5 rounded bg-gray-800 disabled:opacity-40 hover:bg-gray-700"
				>▶</button>
			</div>
		</div>
	{/if}
</div>
