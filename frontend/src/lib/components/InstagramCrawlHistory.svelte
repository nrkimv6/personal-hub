<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { collectApi } from '$lib/api';
	import type { CrawlHistoryItem } from '$lib/types';
	import { Button } from '$lib/components/ui';

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

	$: {
		hasProcessingItems = items.some((i) => i.status === 'pending' || i.status === 'processing');
		if (hasProcessingItems && !refreshInterval) {
			refreshInterval = setInterval(() => {
				fetchHistory(true);
			}, 5000);
		} else if (!hasProcessingItems && refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	export async function fetchHistory(silent = false) {
		try {
			if (!silent) loading = true;
			const response = await collectApi.getInstagramCrawlHistory({
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
				return { class: 'bg-primary-light text-primary', text: '피드' };
			case 'single_post':
				return { class: 'bg-purple-light text-purple-800', text: '재크롤' };
			case 'single_post_url':
				return { class: 'bg-primary-light text-indigo-800', text: 'URL' };
			default:
				return { class: 'bg-muted text-foreground', text: type };
		}
	}

	function getRequestedByBadge(by: string): { class: string; text: string } {
		switch (by) {
			case 'scheduler':
				return { class: 'bg-primary-light text-primary', text: '스케줄' };
			case 'manual':
				return { class: 'bg-success-light text-success', text: '수동' };
			case 'retry':
				return { class: 'bg-warning-light text-warning-foreground', text: '재시도' };
			default:
				return { class: 'bg-background text-foreground', text: by };
		}
	}

	function getStatusBadge(s: string): { class: string; text: string } {
		switch (s) {
			case 'pending':
				return { class: 'bg-muted text-muted-foreground', text: '대기' };
			case 'processing':
				return { class: 'bg-warning-light text-warning-foreground', text: '처리중' };
			case 'completed':
				return { class: 'bg-success-light text-success', text: '완료' };
			case 'failed':
				return { class: 'bg-error-light text-error', text: '실패' };
			default:
				return { class: 'bg-muted text-muted-foreground', text: s };
		}
	}

	function getResultSummary(item: CrawlHistoryItem): string {
		if (item.status === 'pending') return '대기 중...';
		if (item.status === 'processing') {
			if (item.crawl_run && (item.crawl_run.total_collected > 0 || item.crawl_run.new_saved > 0)) {
				return `${item.crawl_run.total_collected}개 수집 / ${item.crawl_run.new_saved}개 신규`;
			}
			return '처리 중...';
		}
		if (item.status === 'failed') return item.error_message || '실패';

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

	let copiedId: number | null = null;
	async function copyUrl(item: CrawlHistoryItem) {
		if (!item.target_url) return;
		try {
			await navigator.clipboard.writeText(item.target_url);
			copiedId = item.id;
			setTimeout(() => {
				copiedId = null;
			}, 2000);
		} catch (e) {
			console.error('Copy failed:', e);
		}
	}

	let retryingId: number | null = null;
	async function retryRequest(item: CrawlHistoryItem) {
		if (retryingId) return;
		try {
			retryingId = item.id;
			await collectApi.retryCrawlRequest(item.id);
			await fetchHistory();
		} catch (e) {
			console.error('Retry failed:', e);
			error = e instanceof Error ? e.message : '재시도 실패';
		} finally {
			retryingId = null;
		}
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

<div>
	<!-- 통계 요약 -->
	<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
		<div class="card text-center">
			<p class="text-2xl font-bold text-foreground">{total}</p>
			<p class="text-sm text-muted-foreground">전체 요청</p>
		</div>
		<div class="card text-center">
			<p class="text-2xl font-bold text-success">
				{items.filter((i) => i.status === 'completed').length}
			</p>
			<p class="text-sm text-muted-foreground">완료</p>
		</div>
		<div class="card text-center">
			<p class="text-2xl font-bold text-warning-foreground">
				{items.filter((i) => i.status === 'pending' || i.status === 'processing').length}
			</p>
			<p class="text-sm text-muted-foreground">진행중</p>
		</div>
		<div class="card text-center">
			<p class="text-2xl font-bold text-error">
				{items.filter((i) => i.status === 'failed').length}
			</p>
			<p class="text-sm text-muted-foreground">실패</p>
		</div>
	</div>

	<!-- 필터 -->
	<div class="card mb-6">
		<div class="flex flex-wrap gap-4 items-center">
			<div>
				<label for="requestType" class="block text-sm font-medium text-foreground mb-1">타입</label>
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
				<label for="requestedBy" class="block text-sm font-medium text-foreground mb-1">출처</label>
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
				<label for="status" class="block text-sm font-medium text-foreground mb-1">상태</label>
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
				<label for="period" class="block text-sm font-medium text-foreground mb-1">기간</label>
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
			<div class="flex items-end">
				{#if hasProcessingItems}
					<span class="text-xs text-warning-foreground flex items-center gap-1">
						<span class="inline-block w-2 h-2 bg-warning rounded-full animate-pulse"></span>
						자동 새로고침 중
					</span>
				{/if}
			</div>
		</div>
	</div>

	<!-- 이력 목록 -->
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if items.length === 0}
		<div class="card text-center py-12">
			<p class="text-muted-foreground">크롤링 이력이 없습니다</p>
		</div>
	{:else}
		<div class="card overflow-hidden">
			<div class="overflow-x-auto">
			<table class="min-w-full divide-y divide-border table-fixed">
				<thead class="bg-background">
					<tr>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-32"
							>요청 시간</th
						>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-24">타입</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-48">URL</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-20">출처</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-20">상태</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-48">결과</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-20">소요시간</th>
						<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase w-16">작업</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-border">
					{#each items as item}
						{@const typeBadge = getRequestTypeBadge(item.request_type)}
						{@const byBadge = getRequestedByBadge(item.requested_by)}
						{@const statusBadge = getStatusBadge(item.status)}
						<tr class="hover:bg-muted">
							<td class="px-4 py-3 text-sm text-foreground">
								{formatDateTime(item.requested_at)}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {typeBadge.class}">
									{typeBadge.text}
								</span>
							</td>
							<td class="px-4 py-3">
								{#if item.target_url}
									<div class="flex items-center gap-1">
										<span class="text-xs text-muted-foreground truncate max-w-[140px]" title={item.target_url}>
											{truncateUrl(item.target_url, 25)}
										</span>
										<button
											onclick={() => copyUrl(item)}
											class="p-1 text-muted-foreground hover:text-primary hover:bg-primary-light rounded transition-colors flex-shrink-0"
											title="URL 복사"
										>
											{#if copiedId === item.id}
												<svg class="w-3.5 h-3.5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
												</svg>
											{:else}
												<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
												</svg>
											{/if}
										</button>
									</div>
								{:else}
									<span class="text-xs text-muted-foreground">-</span>
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
							<td class="px-4 py-3 text-sm text-muted-foreground max-w-[200px]">
								<div class="truncate" title={item.error_message || getResultSummary(item)}>
									{getResultSummary(item)}
								</div>
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">
								{#if item.crawl_run?.duration_seconds}
									{formatDuration(item.crawl_run.duration_seconds)}
								{:else}
									-
								{/if}
							</td>
							<td class="px-4 py-3 text-center">
								<div class="flex justify-center gap-1">
									{#if item.status === 'failed' || item.status === 'completed'}
										<button
											onclick={() => retryRequest(item)}
											disabled={retryingId === item.id}
											class="p-1.5 text-muted-foreground hover:text-warning hover:bg-warning-light rounded transition-colors disabled:opacity-50"
											title="재시도"
										>
											{#if retryingId === item.id}
												<svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
													<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
												</svg>
											{:else}
												<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
												</svg>
											{/if}
										</button>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
			</div>
		</div>

		<!-- 페이지네이션 -->
		{#if totalPages > 1}
			<div class="flex justify-center items-center gap-2 mt-6">
				<Button
					onclick={() => {
						page = Math.max(1, page - 1);
						fetchHistory();
					}}
					disabled={page === 1}
					variant="secondary"
					size="sm"
				>
					이전
				</Button>
				<span class="text-sm text-muted-foreground">
					{page} / {totalPages}
				</span>
				<Button
					onclick={() => {
						page = Math.min(totalPages, page + 1);
						fetchHistory();
					}}
					disabled={page === totalPages}
					variant="secondary"
					size="sm"
				>
					다음
				</Button>
			</div>
		{/if}
	{/if}
</div>
