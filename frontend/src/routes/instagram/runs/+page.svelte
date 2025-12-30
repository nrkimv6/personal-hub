<script lang="ts">
	import { onMount } from 'svelte';
	import { instagramApi } from '$lib/api';
	import type { InstagramCrawlRunExtended, InstagramRunStats } from '$lib/types';

	let runs: InstagramCrawlRunExtended[] = [];
	let stats: InstagramRunStats | null = null;
	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let page = 1;
	let limit = 20;
	let total = 0;

	// 필터
	let period: 'today' | 'week' | 'month' | 'all' = 'week';
	let status: 'all' | 'success' | 'failed' = 'all';

	$: totalPages = Math.ceil(total / limit);

	async function fetchRuns() {
		try {
			loading = true;
			const response = await instagramApi.getRunsPaginated({
				page,
				limit,
				period: period === 'all' ? undefined : period,
				status: status === 'all' ? undefined : status
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
			stats = await instagramApi.getRunStats();
		} catch (e) {
			console.error('Stats fetch error:', e);
		}
	}

	function handleFilterChange() {
		page = 1;
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

	function getStatusBadge(success: boolean, errorMessage: string | null): { class: string; text: string } {
		if (success) {
			return { class: 'bg-green-100 text-green-800', text: '성공' };
		}
		return { class: 'bg-red-100 text-red-800', text: errorMessage ? '오류' : '실패' };
	}

	function getTriggerLabel(trigger: string): string {
		switch (trigger) {
			case 'schedule': return '스케줄';
			case 'manual': return '수동';
			case 'request': return '요청';
			default: return trigger;
		}
	}

	onMount(() => {
		fetchRuns();
		fetchStats();
	});
</script>

<div class="p-6">
	<div class="mb-6 flex justify-between items-center">
		<div>
			<h2 class="text-2xl font-bold text-gray-900">수집 이력</h2>
			<p class="text-sm text-gray-500 mt-1">Instagram 크롤링 실행 기록</p>
		</div>
		<a href="/instagram" class="btn btn-secondary btn-sm">대시보드로</a>
	</div>

	<!-- 통계 요약 -->
	{#if stats}
		<div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
			<div class="card text-center">
				<p class="text-2xl font-bold text-gray-900">{stats.total_runs}</p>
				<p class="text-sm text-gray-500">전체 실행</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-green-600">{stats.success_runs}</p>
				<p class="text-sm text-gray-500">성공</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-red-600">{stats.failed_runs}</p>
				<p class="text-sm text-gray-500">실패</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-blue-600">{stats.total_collected}</p>
				<p class="text-sm text-gray-500">총 수집</p>
			</div>
		</div>
	{/if}

	<!-- 필터 -->
	<div class="card mb-6">
		<div class="flex flex-wrap gap-4 items-center">
			<div>
				<label for="period" class="block text-sm font-medium text-gray-700 mb-1">기간</label>
				<select
					id="period"
					bind:value={period}
					onchange={handleFilterChange}
					class="input input-sm w-32"
				>
					<option value="today">오늘</option>
					<option value="week">최근 7일</option>
					<option value="month">최근 30일</option>
					<option value="all">전체</option>
				</select>
			</div>
			<div>
				<label for="status" class="block text-sm font-medium text-gray-700 mb-1">상태</label>
				<select
					id="status"
					bind:value={status}
					onchange={handleFilterChange}
					class="input input-sm w-32"
				>
					<option value="all">전체</option>
					<option value="success">성공</option>
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
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">트리거</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">수집</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">신규</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">소요 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">계정</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-gray-200">
					{#each runs as run}
						{@const badge = getStatusBadge(run.success, run.error_message)}
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
										{run.error_message.substring(0, 30)}...
									</span>
								{/if}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600">
								{getTriggerLabel(run.trigger_type)}
							</td>
							<td class="px-4 py-3 text-sm text-gray-900 text-right">
								{run.total_collected}
							</td>
							<td class="px-4 py-3 text-sm text-blue-600 text-right font-medium">
								{run.new_saved}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600 text-right">
								{formatDuration(run.duration_seconds)}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600">
								{run.accounts_processed || '-'}개
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
					onclick={() => { page = Math.max(1, page - 1); fetchRuns(); }}
					disabled={page === 1}
					class="btn btn-secondary btn-sm"
				>
					이전
				</button>
				<span class="text-sm text-gray-600">
					{page} / {totalPages}
				</span>
				<button
					onclick={() => { page = Math.min(totalPages, page + 1); fetchRuns(); }}
					disabled={page === totalPages}
					class="btn btn-secondary btn-sm"
				>
					다음
				</button>
			</div>
		{/if}
	{/if}
</div>
