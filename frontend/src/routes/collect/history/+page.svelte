<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { collectApi, type CrawlHistoryItem, type CrawlHistoryFilters } from '$lib/api';

	let items: CrawlHistoryItem[] = [];
	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let page = 1;
	let limit = 20;
	let total = 0;
	let totalPages = 0;

	// 필터
	let sourceType: string = '';
	let status: string = '';
	let period: string = 'week';

	// 자동 새로고침
	let refreshInterval: ReturnType<typeof setInterval> | null = null;
	let hasProcessingItems = false;

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

	async function fetchHistory(silent = false) {
		try {
			if (!silent) loading = true;
			const params: CrawlHistoryFilters = { page, limit };
			if (sourceType) params.source_type = sourceType;
			if (status) params.status = status;
			if (period) params.period = period;

			const result = await collectApi.getHistory(params);
			items = result.items;
			total = result.total;
			totalPages = result.total_pages;
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

	function getHistoryTypeBadge(type: string): { class: string; text: string } {
		switch (type) {
			case 'request':
				return { class: 'bg-primary-light text-primary', text: '요청' };
			case 'schedule_run':
				return { class: 'bg-purple-light text-purple-800', text: '스케줄' };
			default:
				return { class: 'bg-muted text-foreground', text: type };
		}
	}

	function getSourceBadge(source: string): { class: string; text: string } {
		switch (source) {
			case 'instagram':
				return { class: 'bg-pink-light text-pink', text: 'Instagram' };
			case 'web':
				return { class: 'bg-primary-light text-primary', text: 'Web' };
			default:
				return { class: 'bg-muted text-foreground', text: source };
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
		if (item.status === 'processing') return '처리 중...';
		if (item.status === 'failed') return item.error_message || '실패';

		if (item.history_type === 'schedule_run') {
			return `${item.collected_count}개 수집 / ${item.saved_count}개 저장`;
		}
		return '완료';
	}

	function truncateUrl(url: string | undefined, maxLen = 40): string {
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

<div>
	<!-- 통계 요약 -->
	<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
		<div class="card text-center">
			<p class="text-2xl font-bold text-foreground">{total}</p>
			<p class="text-sm text-muted-foreground">전체</p>
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
				<label for="sourceType" class="block text-sm font-medium text-foreground mb-1">소스</label>
				<select
					id="sourceType"
					bind:value={sourceType}
					onchange={handleFilterChange}
					class="input input-sm w-32"
				>
					<option value="">전체</option>
					<option value="instagram">Instagram</option>
					<option value="web">Web</option>
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
					<option value="">전체</option>
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
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-28">시간</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-20">타입</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-24">소스</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-48">대상</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-20">상태</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-40">결과</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase w-20">소요시간</th>
						</tr>
					</thead>
					<tbody class="bg-white divide-y divide-border">
						{#each items as item}
							{@const typeBadge = getHistoryTypeBadge(item.history_type)}
							{@const sourceBadge = getSourceBadge(item.source_type)}
							{@const statusBadge = getStatusBadge(item.status)}
							<tr class="hover:bg-muted">
								<td class="px-4 py-3 text-sm text-foreground">
									{formatDateTime(item.started_at)}
								</td>
								<td class="px-4 py-3">
									<span class="px-2 py-1 text-xs rounded-full {typeBadge.class}">
										{typeBadge.text}
									</span>
								</td>
								<td class="px-4 py-3">
									<span class="px-2 py-1 text-xs rounded-full {sourceBadge.class}">
										{sourceBadge.text}
									</span>
								</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">
									{#if item.history_type === 'schedule_run'}
										<span class="font-medium">{item.schedule_name || '-'}</span>
									{:else}
										<span class="text-xs truncate max-w-[180px] block" title={item.url}>
											{truncateUrl(item.url, 30)}
										</span>
									{/if}
								</td>
								<td class="px-4 py-3">
									<span class="px-2 py-1 text-xs rounded-full {statusBadge.class}">
										{statusBadge.text}
									</span>
								</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">
									<div class="truncate max-w-[160px]" title={item.error_message || getResultSummary(item)}>
										{getResultSummary(item)}
									</div>
								</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">
									{formatDuration(item.duration_seconds)}
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
				<button
					onclick={() => {
						page = Math.max(1, page - 1);
						fetchHistory();
					}}
					disabled={page === 1}
					class="btn btn-secondary btn-sm"
				>
					이전
				</Button>
				<span class="text-sm text-muted-foreground">
					{page} / {totalPages}
				</span>
				<button
					onclick={() => {
						page = Math.min(totalPages, page + 1);
						fetchHistory();
					}}
					disabled={page === totalPages}
					class="btn btn-secondary btn-sm"
				>
					다음
				</Button>
			</div>
		{/if}
	{/if}
</div>
