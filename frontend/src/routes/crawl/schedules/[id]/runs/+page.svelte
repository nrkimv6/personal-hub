<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { crawlApi } from '$lib/api';
	import type { CrawlSchedule, CrawlScheduleRun, CrawlRunStats } from '$lib/types';

	let schedule: CrawlSchedule | null = null;
	let runs: CrawlScheduleRun[] = [];
	let stats: CrawlRunStats | null = null;
	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let currentPage = 1;
	let limit = 20;
	let total = 0;

	// 필터
	let status: string = '';

	$: scheduleId = parseInt($page.params.id);
	$: totalPages = Math.ceil(total / limit);

	async function fetchSchedule() {
		try {
			schedule = await crawlApi.getSchedule(scheduleId);
		} catch (e) {
			console.error('Schedule fetch error:', e);
		}
	}

	async function fetchRuns() {
		try {
			loading = true;
			const response = await crawlApi.getScheduleRuns(scheduleId, {
				page: currentPage,
				limit,
				status: status || undefined
			});
			runs = response.items ?? [];
			total = response.total ?? 0;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function fetchStats() {
		try {
			stats = await crawlApi.getScheduleStats(scheduleId, 7);
		} catch (e) {
			console.error('Stats fetch error:', e);
		}
	}

	function handleFilterChange() {
		currentPage = 1;
		fetchRuns();
	}

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				year: 'numeric',
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function formatDuration(seconds: number | null): string {
		if (seconds === null || seconds === undefined) return '-';
		if (seconds < 60) return `${seconds}초`;
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}분 ${secs}초`;
	}

	function getStatusBadge(status: string): { class: string; text: string } {
		switch (status) {
			case 'running':
				return { class: 'bg-blue-100 text-blue-800', text: '실행중' };
			case 'completed':
				return { class: 'bg-green-100 text-green-800', text: '완료' };
			case 'failed':
				return { class: 'bg-red-100 text-red-800', text: '실패' };
			default:
				return { class: 'bg-gray-100 text-gray-800', text: status };
		}
	}

	function getStopReasonLabel(reason: string | null): string {
		if (!reason) return '-';
		switch (reason) {
			case 'max_posts_reached': return '최대 수집';
			case 'duplicate_stop': return '중복 종료';
			case 'error': return '오류';
			case 'manual': return '수동 종료';
			default: return reason;
		}
	}

	onMount(() => {
		fetchSchedule();
		fetchRuns();
		fetchStats();
	});
</script>

<div class="p-6 max-w-7xl mx-auto">
	<div class="mb-6 flex justify-between items-center">
		<div>
			<h2 class="text-2xl font-bold text-gray-900">
				{#if schedule}
					{schedule.display_name || schedule.name}
				{:else}
					스케줄 #{scheduleId}
				{/if}
				실행 이력
			</h2>
			<p class="text-sm text-gray-500 mt-1">스케줄 실행 기록</p>
		</div>
		<a href="/crawl/schedules" class="btn btn-secondary btn-sm">스케줄 목록</a>
	</div>

	<!-- 통계 요약 -->
	{#if stats}
		<div class="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
			<div class="card text-center">
				<p class="text-2xl font-bold text-gray-900">{stats.total_runs}</p>
				<p class="text-sm text-gray-500">전체 실행</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-green-600">{stats.completed_runs}</p>
				<p class="text-sm text-gray-500">완료</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-red-600">{stats.failed_runs}</p>
				<p class="text-sm text-gray-500">실패</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-blue-600">{stats.success_rate.toFixed(1)}%</p>
				<p class="text-sm text-gray-500">성공률</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-purple-600">{stats.total_saved}</p>
				<p class="text-sm text-gray-500">총 저장</p>
			</div>
		</div>
	{/if}

	<!-- 필터 -->
	<div class="card mb-6">
		<div class="flex flex-wrap gap-4 items-center">
			<div>
				<label for="status" class="block text-sm font-medium text-gray-700 mb-1">상태</label>
				<select
					id="status"
					bind:value={status}
					onchange={handleFilterChange}
					class="input input-sm w-32"
				>
					<option value="">전체</option>
					<option value="running">실행중</option>
					<option value="completed">완료</option>
					<option value="failed">실패</option>
				</select>
			</div>
		</div>
	</div>

	<!-- 실행 목록 -->
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if !runs || runs.length === 0}
		<div class="card text-center py-12">
			<p class="text-gray-500">실행 기록이 없습니다</p>
		</div>
	{:else}
		<div class="card overflow-hidden">
			<table class="min-w-full divide-y divide-gray-200">
				<thead class="bg-gray-50">
					<tr>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">시작 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">수집</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">저장</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">종료 사유</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">소요 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">워커</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-gray-200">
					{#each runs as run}
						{@const badge = getStatusBadge(run.status)}
						<tr class="hover:bg-gray-50">
							<td class="px-4 py-3 text-sm text-gray-900">
								{formatDateTime(run.started_at)}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {badge.class}">
									{badge.text}
								</span>
								{#if run.error_message}
									<span class="ml-2 text-xs text-red-500" title={run.error_message}>
										{run.error_message.substring(0, 25)}...
									</span>
								{/if}
							</td>
							<td class="px-4 py-3 text-sm text-gray-900 text-right">
								{run.collected_count}
							</td>
							<td class="px-4 py-3 text-sm text-blue-600 text-right font-medium">
								{run.saved_count}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600">
								{getStopReasonLabel(run.stop_reason)}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600 text-right">
								{formatDuration(run.duration_seconds)}
							</td>
							<td class="px-4 py-3 text-sm text-gray-500">
								{run.worker_id || '-'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- 페이지네이션 -->
		{#if totalPages > 1}
			<div class="flex justify-center items-center gap-2 mt-6">
				<button
					onclick={() => { currentPage = Math.max(1, currentPage - 1); fetchRuns(); }}
					disabled={currentPage === 1}
					class="btn btn-secondary btn-sm"
				>
					이전
				</button>
				<span class="text-sm text-gray-600">
					{currentPage} / {totalPages}
				</span>
				<button
					onclick={() => { currentPage = Math.min(totalPages, currentPage + 1); fetchRuns(); }}
					disabled={currentPage === totalPages}
					class="btn btn-secondary btn-sm"
				>
					다음
				</button>
			</div>
		{/if}
	{/if}
</div>
