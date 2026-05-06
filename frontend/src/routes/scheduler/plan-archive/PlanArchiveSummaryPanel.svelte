<script lang="ts">
	import { Pause, Play, RefreshCw, AlertTriangle, CheckCircle, Clock } from 'lucide-svelte';
	import type { ArchiveScheduleDashboardResponse } from '$lib/api/plan-records';

	interface Props {
		dashboard: ArchiveScheduleDashboardResponse | null;
		loading?: boolean;
		error?: string | null;
		staleAt?: string | null;
		onPause?: () => void;
		onResume?: () => void;
		onRefresh?: () => void;
		pausing?: boolean;
	}

	let {
		dashboard,
		loading = false,
		error = null,
		staleAt = null,
		onPause,
		onResume,
		onRefresh,
		pausing = false,
	}: Props = $props();

	const sched = $derived(dashboard?.schedule as Record<string, unknown> | null ?? null);
	const enabled = $derived(sched ? Boolean(sched['enabled']) : null);
	const qs = $derived(dashboard?.queue_summary);
	const readiness = $derived(dashboard?.retrieval_readiness as Record<string, unknown> | null ?? null);

	const failureCategories = ['timeout', 'quota', 'parse', 'network', 'other'];
</script>

<div class="rounded-lg border border-border bg-card p-4 space-y-3">
	<div class="flex items-center justify-between">
		<h2 class="text-base font-semibold">Archive Schedule 현황</h2>
		<div class="flex items-center gap-2">
			{#if staleAt}
				<span class="text-xs text-yellow-600">마지막 갱신: {staleAt}</span>
			{/if}
			<button
				class="rounded p-1 text-muted-foreground hover:bg-muted"
				onclick={onRefresh}
				disabled={loading}
				title="새로고침"
			>
				<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
			</button>
		</div>
	</div>

	{#if error}
		<div class="flex items-center gap-2 rounded bg-destructive/10 px-3 py-2 text-sm text-destructive">
			<AlertTriangle class="h-4 w-4 shrink-0" />
			<span>{error}</span>
			{#if staleAt}<span class="ml-auto text-xs opacity-70">stale</span>{/if}
		</div>
	{/if}

	{#if loading && !dashboard}
		<div class="space-y-2">
			{#each Array(3) as _}
				<div class="h-5 w-full animate-pulse rounded bg-muted"></div>
			{/each}
		</div>
	{:else if dashboard}
		<!-- Schedule status -->
		<div class="flex items-center gap-3 text-sm">
			{#if enabled === true}
				<span class="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
					<CheckCircle class="h-3 w-3" />활성
				</span>
			{:else if enabled === false}
				<span class="inline-flex items-center gap-1 rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800">
					<Pause class="h-3 w-3" />일시정지
				</span>
			{/if}
			{#if sched}
				{#if sched['next_run_at']}
					<span class="flex items-center gap-1 text-muted-foreground">
						<Clock class="h-3 w-3" />다음 실행: {sched['next_run_at']}
					</span>
				{/if}
				{#if sched['last_run_at']}
					<span class="text-muted-foreground">마지막: {sched['last_run_at']}</span>
				{/if}
			{/if}
			<div class="ml-auto flex gap-1">
				{#if enabled !== false}
					<button
						class="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs hover:bg-muted disabled:opacity-50"
						onclick={onPause}
						disabled={pausing}
					>
						<Pause class="h-3 w-3" />정지
					</button>
				{:else}
					<button
						class="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs hover:bg-muted disabled:opacity-50"
						onclick={onResume}
						disabled={pausing}
					>
						<Play class="h-3 w-3" />재개
					</button>
				{/if}
			</div>
		</div>

		<!-- Queue summary -->
		{#if qs}
			<div class="grid grid-cols-4 gap-2 text-center text-sm">
				<div class="rounded bg-muted/50 p-2">
					<div class="text-lg font-bold">{qs.pending}</div>
					<div class="text-xs text-muted-foreground">대기</div>
				</div>
				<div class="rounded bg-muted/50 p-2">
					<div class="text-lg font-bold">{qs.processing}</div>
					<div class="text-xs text-muted-foreground">처리중</div>
				</div>
				<div class="rounded bg-muted/50 p-2">
					<div class="text-lg font-bold text-destructive">{qs.failed}</div>
					<div class="text-xs text-muted-foreground">실패</div>
				</div>
				<div class="rounded bg-muted/50 p-2">
					<div class="text-lg font-bold text-green-600">{qs.completed_24h}</div>
					<div class="text-xs text-muted-foreground">24h 완료</div>
				</div>
			</div>
			<!-- Failure category chips -->
			{#if Object.keys(qs.recent_failures_by_category).length > 0}
				<div class="flex flex-wrap gap-1">
					{#each failureCategories as cat}
						{@const count = qs.recent_failures_by_category[cat] ?? 0}
						{#if count > 0}
							<span class="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700">
								{cat} {count}
							</span>
						{/if}
					{/each}
				</div>
			{/if}
		{/if}

		<!-- Readiness -->
		{#if readiness && !readiness['ready']}
			<div class="rounded bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
				실행 준비 미완료: {readiness['missing_tables'] ? JSON.stringify(readiness['missing_tables']) : '테이블 없음'}
			</div>
		{/if}
	{/if}
</div>
