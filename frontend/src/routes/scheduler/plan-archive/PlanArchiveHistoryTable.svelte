<script lang="ts">
	import { RefreshCw, ChevronLeft, ChevronRight } from 'lucide-svelte';
	import { createPagePagination } from '$lib/utils/pagination.svelte';
	import { archiveScheduleApi, type ArchiveScheduleRunRow, type ArchiveExecutionAttemptRow } from '$lib/api/plan-records';

	let scheduleItems = $state<ArchiveScheduleRunRow[]>([]);
	let attemptItems = $state<ArchiveExecutionAttemptRow[]>([]);
	let loadingSchedule = $state(false);
	let loadingAttempt = $state(false);
	let errorSchedule = $state<string | null>(null);
	let errorAttempt = $state<string | null>(null);

	let scheduleStatusFilter = $state('');
	let attemptStatusFilter = $state('');

	const schedulePager = createPagePagination(20);
	const attemptPager = createPagePagination(20);

	function attemptTargetText(a: ArchiveExecutionAttemptRow): string {
		const model = a.model ?? 'default';
		if (a.engine && a.profile_name) return `${a.engine}/${a.profile_name}/${model}`;
		if (a.provider) return `${a.provider}/${model}`;
		return '—';
	}

	async function loadScheduleRuns() {
		loadingSchedule = true;
		errorSchedule = null;
		try {
			const res = await archiveScheduleApi.listScheduleRuns({
				status: scheduleStatusFilter || undefined,
				page: schedulePager.page,
				page_size: 20,
			});
			scheduleItems = res.items;
			schedulePager.total = res.total;
		} catch (e) {
			errorSchedule = e instanceof Error ? e.message : '로드 실패';
		} finally {
			loadingSchedule = false;
		}
	}

	async function loadAttempts() {
		loadingAttempt = true;
		errorAttempt = null;
		try {
			const res = await archiveScheduleApi.listExecutionAttempts({
				status: attemptStatusFilter || undefined,
				page: attemptPager.page,
				page_size: 20,
			});
			attemptItems = res.items;
			attemptPager.total = res.total;
		} catch (e) {
			errorAttempt = e instanceof Error ? e.message : '로드 실패';
		} finally {
			loadingAttempt = false;
		}
	}

	$effect(() => { schedulePager.reset(); loadScheduleRuns(); });
	$effect(() => { attemptPager.reset(); loadAttempts(); });
</script>

<div class="space-y-6">
	<!-- Schedule Runs -->
	<section class="space-y-2">
		<div class="flex items-center gap-2">
			<h3 class="text-sm font-medium">Schedule Run 이력</h3>
			<select
				class="ml-auto rounded border border-border bg-background px-2 py-0.5 text-xs"
				bind:value={scheduleStatusFilter}
				onchange={() => { schedulePager.reset(); loadScheduleRuns(); }}
			>
				<option value="">전체</option>
				{#each ['completed', 'failed', 'running'] as s}
					<option value={s}>{s}</option>
				{/each}
			</select>
			<button class="rounded p-0.5 hover:bg-muted" onclick={loadScheduleRuns}>
				<RefreshCw class="h-3 w-3 {loadingSchedule ? 'animate-spin' : ''}" />
			</button>
		</div>
		{#if errorSchedule}
			<div class="rounded bg-destructive/10 px-3 py-1 text-xs text-destructive">
				{errorSchedule} — <button class="underline" onclick={loadScheduleRuns}>재시도</button>
			</div>
		{:else if scheduleItems.length === 0 && !loadingSchedule}
			<div class="rounded bg-muted/30 py-4 text-center text-xs text-muted-foreground">이력 없음</div>
		{:else}
			<table class="w-full text-xs">
				<thead>
					<tr class="border-b border-border text-left text-muted-foreground">
						<th class="px-2 py-1">ID</th>
						<th class="px-2 py-1">상태</th>
						<th class="px-2 py-1">시작</th>
						<th class="px-2 py-1">종료</th>
						<th class="px-2 py-1">사유</th>
					</tr>
				</thead>
				<tbody>
					{#each scheduleItems as r}
						<tr class="border-b border-border/50 hover:bg-muted/30">
							<td class="px-2 py-1">{r.id}</td>
							<td class="px-2 py-1">
								<span class="rounded-full px-1.5 py-0.5 {r.status === 'completed' ? 'bg-green-100 text-green-700' : r.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-muted'}">{r.status}</span>
							</td>
							<td class="px-2 py-1 whitespace-nowrap">{r.started_at?.slice(0, 16) ?? '—'}</td>
							<td class="px-2 py-1 whitespace-nowrap">{r.finished_at?.slice(0, 16) ?? '—'}</td>
							<td class="px-2 py-1">{r.stop_reason ?? r.error_message?.slice(0, 40) ?? '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<div class="flex items-center justify-between text-xs text-muted-foreground">
				<span>총 {schedulePager.total}건</span>
				<div class="flex items-center gap-1">
					<button disabled={schedulePager.page <= 1} onclick={() => { schedulePager.page -= 1; loadScheduleRuns(); }} class="rounded p-0.5 hover:bg-muted disabled:opacity-40">
						<ChevronLeft class="h-4 w-4" />
					</button>
					<span>{schedulePager.page}/{schedulePager.totalPages}</span>
					<button disabled={schedulePager.page >= schedulePager.totalPages} onclick={() => { schedulePager.page += 1; loadScheduleRuns(); }} class="rounded p-0.5 hover:bg-muted disabled:opacity-40">
						<ChevronRight class="h-4 w-4" />
					</button>
				</div>
			</div>
		{/if}
	</section>

	<!-- Execution Attempts -->
	<section class="space-y-2">
		<div class="flex items-center gap-2">
			<h3 class="text-sm font-medium">실행 Attempt 이력</h3>
			<select
				class="ml-auto rounded border border-border bg-background px-2 py-0.5 text-xs"
				bind:value={attemptStatusFilter}
				onchange={() => { attemptPager.reset(); loadAttempts(); }}
			>
				<option value="">전체</option>
				{#each ['completed', 'failed', 'running', 'pending'] as s}
					<option value={s}>{s}</option>
				{/each}
			</select>
			<button class="rounded p-0.5 hover:bg-muted" onclick={loadAttempts}>
				<RefreshCw class="h-3 w-3 {loadingAttempt ? 'animate-spin' : ''}" />
			</button>
		</div>
		{#if errorAttempt}
			<div class="rounded bg-destructive/10 px-3 py-1 text-xs text-destructive">
				{errorAttempt} — <button class="underline" onclick={loadAttempts}>재시도</button>
			</div>
		{:else if attemptItems.length === 0 && !loadingAttempt}
			<div class="rounded bg-muted/30 py-4 text-center text-xs text-muted-foreground">이력 없음</div>
		{:else}
			<table class="w-full text-xs">
				<thead>
					<tr class="border-b border-border text-left text-muted-foreground">
						<th class="px-2 py-1">ID</th>
						<th class="px-2 py-1">상태</th>
						<th class="px-2 py-1">target</th>
						<th class="px-2 py-1">record</th>
						<th class="px-2 py-1">시작</th>
						<th class="px-2 py-1">오류</th>
					</tr>
				</thead>
				<tbody>
					{#each attemptItems as a}
						<tr class="border-b border-border/50 hover:bg-muted/30">
							<td class="px-2 py-1">{a.id}</td>
							<td class="px-2 py-1">
								<span class="rounded-full px-1.5 py-0.5 {a.status === 'completed' ? 'bg-green-100 text-green-700' : a.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-muted'}">{a.status}</span>
							</td>
							<td class="px-2 py-1" title={attemptTargetText(a)}>{attemptTargetText(a)}</td>
							<td class="px-2 py-1">{a.record_id ?? '—'}</td>
							<td class="px-2 py-1 whitespace-nowrap">{a.requested_at?.slice(0, 16) ?? '—'}</td>
							<td class="px-2 py-1">{a.error_message?.slice(0, 40) ?? '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
			<div class="flex items-center justify-between text-xs text-muted-foreground">
				<span>총 {attemptPager.total}건</span>
				<div class="flex items-center gap-1">
					<button disabled={attemptPager.page <= 1} onclick={() => { attemptPager.page -= 1; loadAttempts(); }} class="rounded p-0.5 hover:bg-muted disabled:opacity-40">
						<ChevronLeft class="h-4 w-4" />
					</button>
					<span>{attemptPager.page}/{attemptPager.totalPages}</span>
					<button disabled={attemptPager.page >= attemptPager.totalPages} onclick={() => { attemptPager.page += 1; loadAttempts(); }} class="rounded p-0.5 hover:bg-muted disabled:opacity-40">
						<ChevronRight class="h-4 w-4" />
					</button>
				</div>
			</div>
		{/if}
	</section>
</div>
