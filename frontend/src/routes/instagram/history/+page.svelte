<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { instagramApi } from '$lib/api';
	import type { CrawlHistoryItem } from '$lib/types';

	let items: CrawlHistoryItem[] = [];
	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let page = 1;
	let limit = 20;
	let total = 0;

	// 필터
	let requestType: 'all' | 'feed' | 'single_post' | 'single_post_url' = 'all';
	let requestedBy: 'all' | 'manual' | 'scheduler' | 'retry' = 'all';
	let status: 'all' | 'pending' | 'processing' | 'completed' | 'failed' = 'all';
	let period: 'all' | 'today' | 'week' | 'month' = 'week';

	// 자동 새로고침
	let refreshInterval: ReturnType<typeof setInterval> | null = null;
	let hasProcessingItems = false;

	$: totalPages = Math.ceil(total / limit);

	// 처리 중인 항목이 있으면 자동 새로고침
	$: {
		hasProcessingItems = items.some(i => i.status === 'pending' || i.status === 'processing');
		if (hasProcessingItems && !refreshInterval) {
			refreshInterval = setInterval(() => {
				fetchHistory(true); // silent refresh
			}, 5000);
		} else if (!hasProcessingItems && refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	async function fetchHistory(silent = false) {
		try {
			if (!silent) loading = true;
			const response = await instagramApi.getCrawlHistory({
				page,
				limit,
				request_type: requestType === 'all' ? undefined : requestType,
				requested_by: requestedBy === 'all' ? undefined : requestedBy,
				status: status === 'all' ? undefined : status,
				period: period === 'all' ? undefined : period
			});
			items = response.items;
			total = response.total;
			error = null;
		} catch (e) {
			if (!silent) error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			if (!silent) loading = false;
		}
	}

	function handleFilterChange() {
		page = 1;
		fetchHistory();
	}

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
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

	function getRequestTypeBadge(type: string): { class: string; text: string } {
		switch (type) {
			case 'feed':
				return { class: 'bg-blue-100 text-blue-800', text: '피드' };
			case 'single_post':
				return { class: 'bg-purple-100 text-purple-800', text: '재크롤' };
			case 'single_post_url':
				return { class: 'bg-indigo-100 text-indigo-800', text: 'URL' };
			default:
				return { class: 'bg-gray-100 text-gray-800', text: type };
		}
	}

	function getRequestedByBadge(by: string): { class: string; text: string } {
		switch (by) {
			case 'scheduler':
				return { class: 'bg-blue-50 text-blue-700', text: '스케줄' };
			case 'manual':
				return { class: 'bg-green-50 text-green-700', text: '수동' };
			case 'retry':
				return { class: 'bg-yellow-50 text-yellow-700', text: '재시도' };
			default:
				return { class: 'bg-gray-50 text-gray-700', text: by };
		}
	}

	function getStatusBadge(s: string): { class: string; text: string } {
		switch (s) {
			case 'pending':
				return { class: 'bg-gray-100 text-gray-600', text: '대기' };
			case 'processing':
				return { class: 'bg-yellow-100 text-yellow-800', text: '처리중' };
			case 'completed':
				return { class: 'bg-green-100 text-green-800', text: '완료' };
			case 'failed':
				return { class: 'bg-red-100 text-red-800', text: '실패' };
			default:
				return { class: 'bg-gray-100 text-gray-600', text: s };
		}
	}

	function getResultSummary(item: CrawlHistoryItem): string {
		if (item.status === 'pending') return '대기 중...';
		if (item.status === 'processing') {
			// 처리 중이어도 진행 상황이 있으면 표시
			if (item.crawl_run && (item.crawl_run.total_collected > 0 || item.crawl_run.new_saved > 0)) {
				return `${item.crawl_run.total_collected}개 수집 / ${item.crawl_run.new_saved}개 신규`;
			}
			return '처리 중...';
		}
		if (item.status === 'failed') return item.error_message || '실패';

		// completed
		if (item.request_type === 'feed' && item.crawl_run) {
			return `${item.crawl_run.total_collected}개 / ${item.crawl_run.new_saved}개 신규`;
		}
		if (item.request_type === 'single_post_url') {
			return '게시물 수집 완료';
		}
		if (item.request_type === 'single_post') {
			return '재크롤링 완료';
		}
		return '완료';
	}

	function truncateUrl(url: string | null, maxLen = 40): string {
		if (!url) return '-';
		if (url.length <= maxLen) return url;
		return url.substring(0, maxLen) + '...';
	}

	onMount(() => {
		fetchHistory();
	});

	onDestroy(() => {
		if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	});
</script>

<div class="p-6">
	<div class="mb-6 flex justify-between items-center">
		<div>
			<h2 class="text-2xl font-bold text-gray-900">크롤링 이력</h2>
			<p class="text-sm text-gray-500 mt-1">모든 크롤링 활동 통합 조회</p>
		</div>
		<div class="flex gap-2 items-center">
			{#if hasProcessingItems}
				<span class="text-xs text-yellow-600 flex items-center gap-1">
					<span class="inline-block w-2 h-2 bg-yellow-500 rounded-full animate-pulse"></span>
					자동 새로고침 중
				</span>
			{/if}
			<button onclick={() => fetchHistory()} class="btn btn-secondary btn-sm">
				새로고침
			</button>
			<a href="/instagram" class="btn btn-secondary btn-sm">대시보드로</a>
		</div>
	</div>

	<!-- 통계 요약 -->
	<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
		<div class="card text-center">
			<p class="text-2xl font-bold text-gray-900">{total}</p>
			<p class="text-sm text-gray-500">전체 요청</p>
		</div>
		<div class="card text-center">
			<p class="text-2xl font-bold text-green-600">
				{items.filter(i => i.status === 'completed').length}
			</p>
			<p class="text-sm text-gray-500">완료</p>
		</div>
		<div class="card text-center">
			<p class="text-2xl font-bold text-yellow-600">
				{items.filter(i => i.status === 'pending' || i.status === 'processing').length}
			</p>
			<p class="text-sm text-gray-500">진행중</p>
		</div>
		<div class="card text-center">
			<p class="text-2xl font-bold text-red-600">
				{items.filter(i => i.status === 'failed').length}
			</p>
			<p class="text-sm text-gray-500">실패</p>
		</div>
	</div>

	<!-- 필터 -->
	<div class="card mb-6">
		<div class="flex flex-wrap gap-4 items-center">
			<div>
				<label for="requestType" class="block text-sm font-medium text-gray-700 mb-1">타입</label>
				<select
					id="requestType"
					bind:value={requestType}
					onchange={handleFilterChange}
					class="input input-sm w-32"
				>
					<option value="all">전체</option>
					<option value="feed">피드</option>
					<option value="single_post">재크롤</option>
					<option value="single_post_url">URL</option>
				</select>
			</div>
			<div>
				<label for="requestedBy" class="block text-sm font-medium text-gray-700 mb-1">출처</label>
				<select
					id="requestedBy"
					bind:value={requestedBy}
					onchange={handleFilterChange}
					class="input input-sm w-32"
				>
					<option value="all">전체</option>
					<option value="scheduler">스케줄</option>
					<option value="manual">수동</option>
					<option value="retry">재시도</option>
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
					<option value="pending">대기</option>
					<option value="processing">처리중</option>
					<option value="completed">완료</option>
					<option value="failed">실패</option>
				</select>
			</div>
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
		</div>
	</div>

	<!-- 이력 목록 -->
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if items.length === 0}
		<div class="card text-center py-12">
			<p class="text-gray-500">크롤링 이력이 없습니다</p>
		</div>
	{:else}
		<div class="card overflow-hidden">
			<table class="min-w-full divide-y divide-gray-200">
				<thead class="bg-gray-50">
					<tr>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">요청 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">타입</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">출처</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">결과</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">소요시간</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-gray-200">
					{#each items as item}
						{@const typeBadge = getRequestTypeBadge(item.request_type)}
						{@const byBadge = getRequestedByBadge(item.requested_by)}
						{@const statusBadge = getStatusBadge(item.status)}
						<tr class="hover:bg-gray-50">
							<td class="px-4 py-3 text-sm text-gray-900">
								{formatDateTime(item.requested_at)}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {typeBadge.class}">
									{typeBadge.text}
								</span>
								{#if item.target_url}
									<span class="ml-2 text-xs text-gray-500" title={item.target_url}>
										{truncateUrl(item.target_url, 25)}
									</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {byBadge.class}">
									{byBadge.text}
								</span>
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {statusBadge.class}">
									{statusBadge.text}
								</span>
							</td>
							<td class="px-4 py-3 text-sm text-gray-600" title={item.error_message || ''}>
								{getResultSummary(item)}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600">
								{#if item.crawl_run?.duration_seconds}
									{formatDuration(item.crawl_run.duration_seconds)}
								{:else}
									-
								{/if}
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
					onclick={() => { page = Math.max(1, page - 1); fetchHistory(); }}
					disabled={page === 1}
					class="btn btn-secondary btn-sm"
				>
					이전
				</button>
				<span class="text-sm text-gray-600">
					{page} / {totalPages}
				</span>
				<button
					onclick={() => { page = Math.min(totalPages, page + 1); fetchHistory(); }}
					disabled={page === totalPages}
					class="btn btn-secondary btn-sm"
				>
					다음
				</button>
			</div>
		{/if}
	{/if}
</div>
