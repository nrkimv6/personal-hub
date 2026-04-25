<script lang="ts">
	import { onMount } from 'svelte';
	import { dailyReportApi, type DailyReportSummary, type DailyReport } from '$lib/api/dev-runner';
	import { Moon, RefreshCw, ChevronDown, AlertTriangle, CheckCircle, XCircle, SkipForward } from 'lucide-svelte';

	let summaries = $state<DailyReportSummary[]>([]);
	let selectedDate = $state<string>('');
	let report = $state<DailyReport | null>(null);
	let loading = $state(false);
	let detailLoading = $state(false);
	let error = $state<string | null>(null);

	async function loadList() {
		loading = true;
		error = null;
		try {
			summaries = await dailyReportApi.list();
			if (summaries.length > 0 && !selectedDate) {
				selectedDate = summaries[0].date;
				await loadReport(selectedDate);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '목록 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function loadReport(date: string) {
		detailLoading = true;
		error = null;
		try {
			report = await dailyReportApi.get(date);
		} catch (e) {
			error = e instanceof Error ? e.message : '보고서 로드 실패';
			report = null;
		} finally {
			detailLoading = false;
		}
	}

	async function onDateChange() {
		if (selectedDate) {
			await loadReport(selectedDate);
		}
	}

	function statusIcon(status: string) {
		switch (status) {
			case 'completed': return CheckCircle;
			case 'failed': return XCircle;
			case 'skipped': return SkipForward;
			default: return AlertTriangle;
		}
	}

	function statusColor(status: string) {
		switch (status) {
			case 'completed': return 'text-green-600';
			case 'failed': return 'text-red-600';
			case 'skipped': return 'text-yellow-600';
			default: return 'text-gray-500';
		}
	}

	function statusBg(status: string) {
		switch (status) {
			case 'completed': return 'bg-green-50 border-green-200';
			case 'failed': return 'bg-red-50 border-red-200';
			case 'skipped': return 'bg-yellow-50 border-yellow-200';
			default: return 'bg-gray-50 border-gray-200';
		}
	}

	onMount(loadList);
</script>

<div class="p-4 lg:p-6 space-y-4">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div class="flex items-center gap-2">
			<Moon size={18} class="text-purple-600" />
			<h2 class="text-base font-semibold">야간 자동 실행 보고서</h2>
		</div>
		<button
			onclick={loadList}
			disabled={loading}
			class="flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-muted transition-colors disabled:opacity-50"
		>
			<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
			새로고침
		</button>
	</div>

	{#if error}
		<div class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
	{/if}

	<!-- 날짜 선택 -->
	{#if summaries.length > 0}
		<div class="flex items-center gap-3">
			<label for="report-date" class="text-sm text-muted-foreground">날짜</label>
			<div class="relative">
				<select
					id="report-date"
					bind:value={selectedDate}
					onchange={onDateChange}
					class="appearance-none rounded-md border border-border bg-background px-3 py-1.5 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
				>
					{#each summaries as s}
						<option value={s.date}>{s.date} (완료 {s.summary?.completed ?? 0}/{s.summary?.total ?? 0})</option>
					{/each}
				</select>
				<ChevronDown size={14} class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
			</div>
		</div>
	{:else if !loading}
		<div class="rounded-lg border border-border bg-muted/30 p-8 text-center text-muted-foreground text-sm">
			아직 자동 실행 보고서가 없습니다.
		</div>
	{/if}

	{#if detailLoading}
		<div class="text-sm text-muted-foreground">보고서 로딩 중...</div>
	{:else if report}
		<!-- 요약 카드 -->
		<div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
			{#each [
				{ label: '전체', value: report.summary.total, color: 'text-foreground' },
				{ label: '완료', value: report.summary.completed, color: 'text-green-600' },
				{ label: '실패', value: report.summary.failed, color: 'text-red-600' },
				{ label: '스킵', value: report.summary.skipped, color: 'text-yellow-600' },
			] as card}
				<div class="rounded-lg border border-border bg-card p-3">
					<div class="text-xs text-muted-foreground mb-1">{card.label}</div>
					<div class="text-2xl font-bold {card.color}">{card.value}</div>
				</div>
			{/each}
		</div>

		<!-- 실행 목록 -->
		{#if report.runs.length === 0}
			<div class="rounded-lg border border-border bg-muted/30 p-6 text-center text-muted-foreground text-sm">
				이 날짜에 자동 실행된 plan이 없습니다.
			</div>
		{:else}
			<div class="space-y-2">
				{#each report.runs as run}
					<div class="rounded-lg border {statusBg(run.status)} p-3 space-y-1">
						<div class="flex items-start justify-between gap-2">
							<div class="flex items-center gap-2 min-w-0">
								<svelte:component this={statusIcon(run.status)} size={15} class={statusColor(run.status)} />
								<span class="font-mono text-sm font-medium truncate">{run.plan_id}</span>
								<span class="text-xs text-muted-foreground shrink-0">scope: {run.scope}</span>
							</div>
							<div class="flex items-center gap-2 shrink-0">
								{#if run.merged}
									<span class="text-xs bg-green-100 text-green-700 rounded px-1.5 py-0.5">머지됨</span>
								{/if}
								{#if run.log_path}
									<a
										href="file:///{run.log_path}"
										class="text-xs text-blue-600 hover:underline"
										target="_blank"
									>로그</a>
								{/if}
							</div>
						</div>
						{#if run.suspicions && run.suspicions.length > 0}
							<ul class="text-xs text-red-700 space-y-0.5 pl-5 list-disc">
								{#each run.suspicions as s}
									<li>{s}</li>
								{/each}
							</ul>
						{/if}
						<div class="text-xs text-muted-foreground">
							{run.started_at ? run.started_at.slice(0, 19).replace('T', ' ') : ''}
							{#if run.ended_at && run.ended_at !== run.started_at}
								→ {run.ended_at.slice(0, 19).replace('T', ' ')}
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>
