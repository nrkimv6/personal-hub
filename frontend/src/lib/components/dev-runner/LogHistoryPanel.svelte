<script lang="ts">
	import { onMount } from 'svelte';
	import { devRunnerLogApi } from '$lib/api/dev-runner';
	import type { RunHistoryItem } from '$lib/api/dev-runner';
	import { createOffsetPagination } from '$lib/utils/pagination.svelte';

	// ── 상태 ──────────────────────────────────────────────────────────────────
	let items = $state<RunHistoryItem[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);

	// 선택된 runner 로그 뷰어
	let selectedRunner = $state<string | null>(null);
	let logLines = $state<string[]>([]);
	let logLoading = $state(false);
	const logPager = createOffsetPagination(500);

	// 목록 페이지네이션
	const listPager = createOffsetPagination(20);

	// ── 목록 로드 ─────────────────────────────────────────────────────────────
	async function loadHistory(reset = false) {
		if (reset) {
			listPager.reset();
			items = [];
		}
		if (loading) return;
		loading = true;
		error = null;
		try {
			const res = await devRunnerLogApi.history(listPager.limit, listPager.offset, true);
			const visibleRuns = res.runs.filter((run) => run.visible !== false);
			items = reset ? visibleRuns : [...items, ...visibleRuns];
			listPager.advance(res.runs.length, res.total);
		} catch (e) {
			error = '히스토리를 불러오지 못했습니다.';
		} finally {
			loading = false;
		}
	}

	// ── 로그 뷰어 ─────────────────────────────────────────────────────────────
	function selectRunner(runnerId: string) {
		selectedRunner = runnerId;
		logLines = [];
		logPager.reset();
		loadLogChunk();
	}

	async function loadLogChunk() {
		if (!selectedRunner || logLoading) return;
		logLoading = true;
		try {
			const res = await devRunnerLogApi.full(selectedRunner, logPager.offset, logPager.limit);
			logLines = [...logLines, ...res.lines];
			logPager.advance(res.lines.length, res.total_lines);
		} catch {
			// 조용히 실패
		} finally {
			logLoading = false;
		}
	}

	function backToList() {
		selectedRunner = null;
		logLines = [];
		logPager.reset();
	}

	// ── 헬퍼 ─────────────────────────────────────────────────────────────────
	function formatTime(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('ko-KR', {
			month: '2-digit', day: '2-digit',
			hour: '2-digit', minute: '2-digit', hour12: false
		});
	}

	function planName(path: string | null): string {
		if (!path) return '(전체 실행)';
		return path.split('/').pop()?.replace(/\.md$/, '') ?? path;
	}

	onMount(() => {
		loadHistory(true);
	});
</script>

{#if selectedRunner}
	<!-- ── 로그 뷰어 ── -->
	<div class="flex flex-col h-full min-h-0">
		<div class="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
			<button
				onclick={backToList}
				class="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
				목록
			</button>
			<span class="text-xs font-mono text-muted-foreground truncate">{selectedRunner}</span>
		</div>
		<pre class="flex-1 min-h-0 overflow-y-auto text-xs font-mono whitespace-pre-wrap p-3 text-foreground leading-relaxed">{logLines.join('\n')}</pre>
		{#if logPager.hasMore}
			<div class="shrink-0 px-3 py-2 border-t border-border">
				<button
					onclick={loadLogChunk}
					disabled={logLoading}
					class="w-full text-xs py-1.5 rounded border border-border hover:bg-secondary transition-colors disabled:opacity-50"
				>
					{logLoading ? '로딩...' : '더 보기'}
				</button>
			</div>
		{/if}
	</div>
{:else}
	<!-- ── 목록 뷰 ── -->
	<div class="flex flex-col h-full min-h-0">
		<div class="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
			<span class="text-xs font-mono text-muted-foreground">로그 히스토리 (user runner)</span>
			<button
				onclick={() => loadHistory(true)}
				disabled={loading}
				class="text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
				title="새로고침"
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
			</button>
		</div>

		<div class="flex-1 min-h-0 overflow-y-auto">
			{#if loading && items.length === 0}
				<div class="flex items-center justify-center h-20 text-xs text-muted-foreground">로딩...</div>
			{:else if error}
				<div class="flex items-center justify-center h-20 text-xs text-destructive">{error}</div>
			{:else if items.length === 0}
				<div class="flex items-center justify-center h-20 text-xs text-muted-foreground">로그 히스토리 없음</div>
			{:else}
				<div class="divide-y divide-border">
					{#each items as item (item.runner_id)}
						<button
							onclick={() => selectRunner(item.runner_id)}
							class="w-full text-left px-3 py-2.5 hover:bg-secondary/50 transition-colors flex flex-col gap-0.5"
						>
							<div class="flex items-center gap-1.5 min-w-0">
								<span class="text-[10px] px-1.5 py-0.5 rounded font-mono shrink-0 {item.status === 'running' ? 'bg-green-100 text-green-800' : 'bg-muted text-muted-foreground'}">
									{item.status === 'running' ? 'RUN' : 'DONE'}
								</span>
								<span class="text-xs font-mono truncate text-foreground">{planName(item.plan_file)}</span>
							</div>
							<div class="flex items-center gap-2 text-[10px] text-muted-foreground font-mono">
								<span>{item.runner_id.slice(0, 8)}</span>
								<span>{formatTime(item.start_time)}</span>
								{#if item.execution_count != null}
									<span class="px-1 py-0.5 rounded bg-indigo-50 text-indigo-600">{item.execution_count}번째</span>
								{/if}
							</div>
						</button>
					{/each}
				</div>
				{#if listPager.hasMore}
					<div class="px-3 py-2">
						<button
							onclick={() => loadHistory()}
							disabled={loading}
							class="w-full text-xs py-1.5 rounded border border-border hover:bg-secondary transition-colors disabled:opacity-50"
						>
							{loading ? '로딩...' : '더 보기'}
						</button>
					</div>
				{/if}
			{/if}
		</div>
	</div>
{/if}
