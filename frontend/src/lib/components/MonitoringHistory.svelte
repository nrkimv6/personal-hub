<script lang="ts">
	import { Badge, Button } from '$lib/components/ui';

	import { onMount } from 'svelte';
	import { monitoringEventApi, businessApi } from '$lib/api';
	import type { MonitoringEvent, MonitoringEventStats, Business } from '$lib/types';

	let monitoringEvents: MonitoringEvent[] = [];
	let monitoringStats: MonitoringEventStats | null = null;
	let businesses: Business[] = [];
	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let page = 1;
	let pageSize = 50;
	let total = 0;
	let totalPages = 1;

	// 필터
	let filters = {
		business_id: '',
		status: '',
		date_from: getTodayDate(),
		date_to: ''
	};

	function getTodayDate(): string {
		return new Date().toISOString().split('T')[0];
	}

	async function loadBusinesses() {
		try {
			businesses = await businessApi.list();
		} catch (e) {
			console.error('업체 목록 로드 실패:', e);
		}
	}

	export async function fetchData() {
		loading = true;
		try {
			const [eventsData, statsData] = await Promise.all([
				monitoringEventApi.list({
					business_id: filters.business_id ? parseInt(filters.business_id) : undefined,
					status: filters.status || undefined,
					date_from: filters.date_from || undefined,
					date_to: filters.date_to || undefined,
					page,
					page_size: pageSize
				}),
				monitoringEventApi.stats({
					business_id: filters.business_id ? parseInt(filters.business_id) : undefined,
					date_from: filters.date_from || undefined,
					date_to: filters.date_to || undefined
				})
			]);
			monitoringEvents = eventsData.items;
			total = eventsData.total;
			totalPages = eventsData.total_pages;
			monitoringStats = statsData;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '모니터링 내역 로드 실패';
		} finally {
			loading = false;
		}
	}

	function handleSearch() {
		page = 1;
		fetchData();
	}

	function clearFilters() {
		filters = {
			business_id: '',
			status: '',
			date_from: getTodayDate(),
			date_to: ''
		};
		page = 1;
		fetchData();
	}

	function getStatusBadgeClass(status: string): string {
		switch (status) {
			case 'success':
				return 'badge-success';
			case 'available':
				return 'badge-info';
			case 'no_slots':
				return 'badge-gray';
			case 'hidden':
			case 'paused':
			case 'closed':
			case 'not_opened':
			case 'inactive':
			case 'inactive_blocked':
			case 'http_302':
			case 'timeout':
				return 'badge-warning';
			case 'page_check_failed':
			case 'http_check_failed':
				return 'badge-gray';
			case 'error':
			case 'failed':
				return 'badge-error';
			default:
				return 'badge-gray';
		}
	}

	function getStatusLabel(status: string): string {
		const labels: Record<string, string> = {
			success: '성공',
			available: '슬롯 있음',
			no_slots: '매진',
			hidden: '숨김',
			paused: '일시중지',
			closed: '비공개',
			not_opened: '미오픈',
			inactive: '비활성화',
			inactive_blocked: '비활성화',
			http_302: '비활성화',
			page_check_failed: '-',
			http_check_failed: '-',
			error: '에러',
			failed: '실패',
			timeout: '타임아웃',
			in_progress: '진행중'
		};
		return labels[status] || status;
	}

	function formatDateTime(dateStr: string | null): string {
		if (!dateStr) return '-';
		return new Date(dateStr).toLocaleString('ko-KR');
	}

	function formatResponseTime(ms: number | null): string {
		if (ms === null) return '-';
		if (ms < 1000) return `${ms.toFixed(0)}ms`;
		return `${(ms / 1000).toFixed(2)}s`;
	}

	function buildBookingUrl(event: MonitoringEvent): string | null {
		if (!event.naver_business_id || !event.naver_biz_item_id) return null;
		return `https://booking.naver.com/booking/13/bizes/${event.naver_business_id}/items/${event.naver_biz_item_id}`;
	}

	let copiedId: number | null = null;
	async function copyUrl(url: string, eventId: number) {
		try {
			await navigator.clipboard.writeText(url);
			copiedId = eventId;
			setTimeout(() => {
				copiedId = null;
			}, 2000);
		} catch (e) {
			console.error('클립보드 복사 실패:', e);
		}
	}

	let expandedEventIds: Record<number, boolean> = {};
	function toggleEventExpand(eventId: number) {
		expandedEventIds[eventId] = !expandedEventIds[eventId];
		expandedEventIds = { ...expandedEventIds };
	}

	function formatJson(data: unknown): string {
		if (!data) return 'null';
		try {
			return JSON.stringify(data, null, 2);
		} catch {
			return String(data);
		}
	}

	async function copyGraphqlResponse(response: unknown) {
		if (!response) return;
		try {
			await navigator.clipboard.writeText(formatJson(response));
			alert('GraphQL 응답이 클립보드에 복사되었습니다.');
		} catch (e) {
			console.error('클립보드 복사 실패:', e);
		}
	}

	onMount(async () => {
		await loadBusinesses();
		await fetchData();
	});
</script>

<div>
	<!-- 통계 -->
	{#if monitoringStats}
		<div class="grid grid-cols-2 md:grid-cols-7 gap-4 mb-6">
			<div class="card p-4 text-center">
				<div class="text-2xl font-bold text-foreground">{monitoringStats.total_checks}</div>
				<div class="text-sm text-muted-foreground">총 체크</div>
			</div>
			<div class="card p-4 text-center">
				<div class="text-2xl font-bold text-success">{monitoringStats.success_count}</div>
				<div class="text-sm text-muted-foreground">성공</div>
			</div>
			<div class="card p-4 text-center">
				<div class="text-2xl font-bold text-primary">{monitoringStats.available_count}</div>
				<div class="text-sm text-muted-foreground">슬롯 발견</div>
			</div>
			<div class="card p-4 text-center">
				<div class="text-2xl font-bold text-muted-foreground">{monitoringStats.no_slots_count}</div>
				<div class="text-sm text-muted-foreground">매진</div>
			</div>
			<div class="card p-4 text-center">
				<div class="text-2xl font-bold text-warning-foreground">
					{(monitoringStats.inactive_count || 0) +
						(monitoringStats.hidden_count || 0) +
						(monitoringStats.paused_count || 0) +
						(monitoringStats.closed_count || 0) +
						(monitoringStats.not_opened_count || 0)}
				</div>
				<div class="text-sm text-muted-foreground">비활성화</div>
			</div>
			<div class="card p-4 text-center">
				<div class="text-2xl font-bold text-error">{monitoringStats.error_count}</div>
				<div class="text-sm text-muted-foreground">에러</div>
			</div>
			<div class="card p-4 text-center">
				<div class="text-2xl font-bold text-foreground">
					{monitoringStats.avg_response_time_ms
						? formatResponseTime(monitoringStats.avg_response_time_ms)
						: '-'}
				</div>
				<div class="text-sm text-muted-foreground">평균 응답</div>
			</div>
		</div>
	{/if}

	<!-- 필터 -->
	<div class="card mb-6">
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
			<div>
				<label for="monitoring-business" class="block text-sm font-medium text-foreground mb-1"
					>업체</label
				>
				<select id="monitoring-business" class="input" bind:value={filters.business_id}>
					<option value="">전체</option>
					{#each businesses as business}
						<option value={business.id}>{business.name}</option>
					{/each}
				</select>
			</div>
			<div>
				<label for="monitoring-status" class="block text-sm font-medium text-foreground mb-1"
					>상태</label
				>
				<select id="monitoring-status" class="input" bind:value={filters.status}>
					<option value="">전체</option>
					<option value="success">성공</option>
					<option value="available">슬롯 있음</option>
					<option value="no_slots">매진</option>
					<option value="hidden">숨김</option>
					<option value="paused">일시중지</option>
					<option value="closed">비공개</option>
					<option value="not_opened">미오픈</option>
					<option value="inactive">비활성화</option>
					<option value="page_check_failed">확인불가</option>
					<option value="error">에러</option>
				</select>
			</div>
			<div>
				<label for="monitoring-date-from" class="block text-sm font-medium text-foreground mb-1"
					>시작일</label
				>
				<input
					id="monitoring-date-from"
					type="date"
					class="input"
					bind:value={filters.date_from}
				/>
			</div>
			<div>
				<label for="monitoring-date-to" class="block text-sm font-medium text-foreground mb-1"
					>종료일</label
				>
				<input id="monitoring-date-to" type="date" class="input" bind:value={filters.date_to} />
			</div>
			<div class="flex items-end gap-2">
				<Button variant="primary" on:click={handleSearch}>검색</Button>
				<Button variant="secondary" on:click={clearFilters}>초기화</Button>
			</div>
		</div>
	</div>

	<!-- 목록 -->
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if monitoringEvents.length === 0}
		<div class="text-center py-12 text-muted-foreground">
			<p class="text-lg">모니터링 내역이 없습니다.</p>
		</div>
	{:else}
		<div class="overflow-x-auto">
			<table class="min-w-full divide-y divide-border">
				<thead class="bg-background">
					<tr>
						<th class="px-3 py-3 text-left text-xs font-medium text-muted-foreground uppercase">시간</th>
						<th class="px-3 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
							>업체/상품</th
						>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">링크</th>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">날짜</th>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">상태</th>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">슬롯</th>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
							>필터 슬롯</th
						>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">예약</th>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">방식</th>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">응답</th>
						<th class="px-2 py-3 text-left text-xs font-medium text-muted-foreground uppercase">에러</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-border">
					{#each monitoringEvents as event}
						<tr class="hover:bg-muted">
							<td class="px-3 py-3 text-sm text-foreground whitespace-nowrap">
								<div class="flex items-center gap-1">
									{#if event.graphql_response}
										<button
											class="w-5 h-5 flex items-center justify-center text-muted-foreground hover:text-primary hover:bg-primary-light rounded transition-colors"
											onclick={() => toggleEventExpand(event.id)}
											title={expandedEventIds[event.id] ? '접기' : '펼치기'}
										>
											<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d={expandedEventIds[event.id] ? 'M19 9l-7 7-7-7' : 'M9 5l7 7-7 7'}
												/>
											</svg>
										</Button>
									{:else}
										<span class="w-5"></span>
									{/if}
									<span>{formatDateTime(event.timestamp)}</span>
								</div>
							</td>
							<td class="px-3 py-3 text-sm">
								<div class="font-medium text-foreground">{event.business_name || '-'}</div>
								<div class="text-muted-foreground">{event.biz_item_name || '-'}</div>
							</td>
							<td class="px-2 py-3 text-sm">
								{#if buildBookingUrl(event)}
									{@const url = buildBookingUrl(event) as string}
									<button
										class="btn btn-xs {copiedId === event.id ? 'btn-success' : 'btn-secondary'}"
										onclick={() => copyUrl(url, event.id)}
										title={url}
									>
										{copiedId === event.id ? '복사됨' : '복사'}
									</Button>
								{:else}
									<span class="text-muted-foreground">-</span>
								{/if}
							</td>
							<td class="px-2 py-3 text-sm text-muted-foreground">{event.schedule_date || '-'}</td>
							<td class="px-2 py-3">
								<span class="badge {getStatusBadgeClass(event.status)}">
									{getStatusLabel(event.status)}
								</span>
							</td>
							<td class="px-2 py-3 text-sm text-muted-foreground">
								{event.original_slot_count ?? event.available_count}개
								{#if event.hash_changed}
									<span class="text-primary text-xs">(변경)</span>
								{/if}
							</td>
							<td class="px-2 py-3 text-sm">
								{#if event.time_range}
									<div class="text-foreground">
										{event.filtered_slot_count ?? '-'}개
										{#if event.target_time_matched}
											<span class="text-success">&#10003;</span>
										{:else}
											<span class="text-muted-foreground">&#10007;</span>
										{/if}
									</div>
									<div class="text-xs text-muted-foreground">{event.time_range}</div>
								{:else}
									<span class="text-muted-foreground">-</span>
								{/if}
							</td>
							<td class="px-2 py-3 text-sm">
								{#if event.booking_triggered}
									{#if event.booking_success === true}
										<Badge variant="success">성공</Badge>
									{:else if event.booking_success === false}
										<Badge variant="error">실패</Badge>
									{:else}
										<Badge variant="warning">시도</Badge>
									{/if}
								{:else}
									<span class="text-muted-foreground">-</span>
								{/if}
							</td>
							<td class="px-2 py-3 text-sm">
								{#if event.fetch_method === 'graphql_api'}
									<Badge variant="info" class="text-xs">API</Badge>
								{:else if event.fetch_method === 'html_scrape'}
									<Badge variant="secondary" class="text-xs">HTML</Badge>
								{:else if event.fetch_method === 'anonymous_api'}
									<span class="badge badge-purple text-xs">익명</span>
								{:else}
									<span class="text-muted-foreground">-</span>
								{/if}
							</td>
							<td class="px-2 py-3 text-sm text-muted-foreground">
								{formatResponseTime(event.response_time_ms)}
							</td>
							<td
								class="px-2 py-3 text-sm text-error max-w-[100px] truncate"
								title={event.error_message || ''}
							>
								{event.error_message || '-'}
							</td>
						</tr>
						<!-- 확장 행 -->
						{#if expandedEventIds[event.id]}
							<tr class="bg-background">
								<td colspan="11" class="px-3 py-4">
									<div class="space-y-3">
										{#if event.graphql_time_ms !== null || event.booking_time_ms !== null}
											<div class="border border-blue-200 rounded-lg bg-primary-light p-3">
												<div class="text-sm font-medium text-primary mb-2">타이밍 상세</div>
												<div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
													<div>
														<span class="text-muted-foreground">GraphQL:</span>
														<span class="font-medium ml-1">
															{event.graphql_time_ms !== null
																? `${event.graphql_time_ms.toFixed(0)}ms`
																: '-'}
														</span>
													</div>
													<div>
														<span class="text-muted-foreground">예약:</span>
														<span class="font-medium ml-1">
															{event.booking_time_ms !== null
																? `${event.booking_time_ms.toFixed(0)}ms`
																: '-'}
														</span>
													</div>
													<div>
														<span class="text-muted-foreground">전체:</span>
														<span class="font-bold ml-1">
															{event.response_time_ms !== null
																? `${event.response_time_ms.toFixed(0)}ms`
																: '-'}
														</span>
													</div>
												</div>
											</div>
										{/if}
										{#if event.graphql_response}
											<div class="border border-border rounded-lg bg-white">
												<div
													class="flex items-center justify-between px-4 py-2 border-b border-border bg-background rounded-t-lg"
												>
													<span class="text-sm font-medium text-foreground">GraphQL 응답</span>
													<button
														class="btn btn-xs btn-secondary"
														onclick={() => copyGraphqlResponse(event.graphql_response)}
													>
														복사
													</Button>
												</div>
												<div class="p-4 max-h-80 overflow-auto">
													<pre
														class="text-xs font-mono text-foreground whitespace-pre-wrap break-words">{formatJson(
															event.graphql_response
														)}</pre>
												</div>
											</div>
										{/if}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>

		<!-- 페이지네이션 -->
		{#if totalPages > 1}
			<div class="mt-4 flex items-center justify-between">
				<div class="text-sm text-muted-foreground">
					총 {total}건 중 {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)}
				</div>
				<div class="flex gap-2">
					<Button variant="secondary"sm
						disabled={page === 1}
						onclick={() => {
							page--;
							fetchData();
						}}
					>
						이전
					</Button>
					<span class="px-3 py-1 text-sm">{page} / {totalPages}</span>
					<Button variant="secondary"sm
						disabled={page === totalPages}
						onclick={() => {
							page++;
							fetchData();
						}}
					>
						다음
					</Button>
				</div>
			</div>
		{/if}
	{/if}
</div>
