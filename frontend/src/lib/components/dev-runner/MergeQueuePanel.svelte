<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerMergeApi, devRunnerLogApi } from '$lib/api/dev-runner';

	interface MergeItem {
		queue_key?: string;
		runner_id: string;
		status: string;
		branch?: string;
		plan_file?: string;
		timestamp?: string;
	}

	let { onCountChange }: { onCountChange?: (count: number) => void } = $props();

	let waitItems: MergeItem[] = $state([]);
	let loading = $state(false);
	let error = $state('');
	let selectedRunnerId = $state<string | null>(null);
	let mergeLogLines = $state<string[]>([]);
	let mergeEventSource: EventSource | null = null;
	let pollTimeout: ReturnType<typeof setTimeout> | null = null;

	const STATUS_COLORS: Record<string, string> = {
		queued:      'bg-yellow-100 text-yellow-800',
		merging:     'bg-purple-100 text-purple-800',
		testing:     'bg-cyan-100 text-cyan-800',
		fixing:      'bg-orange-100 text-orange-800',
		merged:      'bg-green-100 text-green-800',
		approval_required: 'bg-yellow-100 text-yellow-900',
		conflict:    'bg-red-100 text-red-800',
		residue_blocked: 'bg-red-100 text-red-800',
		done:        'bg-green-100 text-green-800',  // legacy
		failed:      'bg-red-100 text-red-800',       // legacy
		test_failed: 'bg-red-100 text-red-800',
		error:       'bg-muted text-muted-foreground',
	};

	const ACTIVE_STATUSES = new Set(['merging', 'queued', 'testing', 'fixing']);

	const activeItems = $derived(waitItems.filter(i => ACTIVE_STATUSES.has(i.status)));
	const doneItems = $derived(waitItems.filter(i => !ACTIVE_STATUSES.has(i.status)));

	function statusColor(status: string): string {
		return STATUS_COLORS[status] ?? 'bg-muted text-muted-foreground';
	}

	function mergeItemKey(item: MergeItem, index: number, section: string): string {
		return item.queue_key ?? `${section}:${item.status}:${item.runner_id}:${item.timestamp ?? ''}:${index}`;
	}

	async function load() {
		loading = true;
		error = '';
		try {
			const raw = await devRunnerMergeApi.queue();
			waitItems = raw as unknown as MergeItem[];
			const queuedCount = waitItems.filter(i => i.status === 'queued').length;
			onCountChange?.(queuedCount);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '불러오기 실패';
		} finally {
			loading = false;
		}
	}

	function schedulePoll() {
		if (pollTimeout) {
			clearTimeout(pollTimeout);
			pollTimeout = null;
		}
		if (document.hidden) return;
		// 활성 항목이 있으면 5초, 없으면 30초
		const interval = activeItems.length > 0 ? 5000 : 30000;
		pollTimeout = setTimeout(async () => {
			await load();
			schedulePoll();
		}, interval);
	}

	function handleVisibilityChange() {
		if (document.hidden) {
			if (pollTimeout) {
				clearTimeout(pollTimeout);
				pollTimeout = null;
			}
		} else {
			// 탭 복귀 시 즉시 fetch 후 폴링 재개
			load().then(() => schedulePoll());
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
		load().then(() => schedulePoll());
		document.addEventListener('visibilitychange', handleVisibilityChange);
	});

	onDestroy(() => {
		if (pollTimeout) clearTimeout(pollTimeout);
		document.removeEventListener('visibilitychange', handleVisibilityChange);
		closeMergeStream();
	});
</script>

<div class="p-4 flex flex-col h-full min-h-0 overflow-hidden">
	<div class="mb-3 flex items-center justify-between shrink-0">
		<div class="flex items-center gap-2">
			<h3 class="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">Merge Queue</h3>
			{#if activeItems.length > 0}
				<span class="flex h-2 w-2 rounded-full bg-purple-500 animate-pulse"></span>
			{/if}
		</div>
		<button
			onclick={load}
			class="p-1 rounded-md hover:bg-muted text-muted-foreground transition-colors disabled:opacity-50"
			disabled={loading}
			title="Refresh"
		>
			<svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5 {loading ? 'animate-spin' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
		</button>
	</div>

	{#if error}
		<div class="bg-red-50 border border-red-100 text-red-600 text-[10px] p-2 rounded mb-3 shrink-0">{error}</div>
	{/if}

	<div class="flex-1 min-h-0 overflow-y-auto pr-0.5 dr-scrollbar-thin">
		{#if activeItems.length === 0 && !loading}
			<div class="flex flex-col items-center justify-center py-10 text-muted-foreground">
				<svg xmlns="http://www.w3.org/2000/svg" class="w-8 h-8 mb-2 opacity-20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6 21V9a9 9 0 0 0 9 9"/><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/></svg>
				<p class="text-[11px] italic">No pending merge tasks</p>
			</div>
		{/if}

		<!-- 활성 섹션 (merging / queued) -->
		{#if activeItems.length > 0}
			<div class="space-y-2.5 pb-2">
				{#each activeItems as item, index (mergeItemKey(item, index, 'active'))}
					<div class="rounded-xl border border-border bg-card text-card-foreground shadow-sm overflow-hidden flex flex-col transition-all hover:shadow-md">
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<div
							class="flex items-center justify-between gap-3 px-3 py-2.5 cursor-pointer hover:bg-muted transition-colors"
							onclick={() => selectRunner(item.runner_id)}
							role="button"
							tabindex="0"
						>
							<div class="flex flex-col min-w-0">
								<span class="text-[10px] font-mono text-muted-foreground truncate mb-0.5">{item.runner_id.slice(0, 12)}...</span>
								<p class="truncate text-[11px] font-bold text-foreground">{item.runner_id}</p>
							</div>
							<span class="rounded-full px-2 py-0.5 text-[9px] font-bold uppercase {statusColor(item.status)}">
								{item.status}
							</span>
						</div>

						<!-- 로그 영역 (선택 시) -->
						{#if selectedRunnerId === item.runner_id}
							<div class="max-h-[200px] overflow-y-auto bg-gray-900 font-mono text-[10px] p-3 border-t border-border" role="log">
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

		<!-- 완료 섹션 (done / failed / test_failed / error) -->
		{#if doneItems.length > 0}
			<div class="mt-3 opacity-50 space-y-2 pb-2">
				<p class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Completed</p>
				{#each doneItems as item, index (mergeItemKey(item, index, 'completed'))}
					<div class="rounded-xl border border-border bg-card text-card-foreground shadow-sm overflow-hidden flex flex-col">
						<div class="flex items-center justify-between gap-3 px-3 py-2">
							<div class="flex flex-col min-w-0">
								<span class="text-[10px] font-mono text-muted-foreground truncate mb-0.5">{item.runner_id.slice(0, 12)}...</span>
								<p class="truncate text-[11px] text-muted-foreground">{item.branch ?? item.runner_id}</p>
							</div>
							<span class="rounded-full px-2 py-0.5 text-[9px] font-bold uppercase {statusColor(item.status)}">
								{item.status}
							</span>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
