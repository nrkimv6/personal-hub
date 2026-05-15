<script lang="ts">
	import { Button } from '$lib/components/ui';

	import { onMount } from 'svelte';
	import { crawlApi } from '$lib/api';
	import type { CrawlRequest, CrawlRequestPaginated } from '$lib/types';

	let requests: CrawlRequest[] = [];
	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let page = 1;
	let limit = 20;
	let total = 0;

	// 필터
	let urlType: string = '';
	let status: string = '';

	$: totalPages = Math.ceil(total / limit);

	async function fetchRequests() {
		try {
			loading = true;
			const response = await crawlApi.getRequests({
				page,
				limit,
				url_type: urlType || undefined,
				status: status || undefined
			});
			requests = response.items ?? [];
			total = response.total ?? 0;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	function handleFilterChange() {
		page = 1;
		fetchRequests();
	}

	async function handleRetry(requestId: number) {
		try {
			await crawlApi.retryRequest(requestId);
			fetchRequests();
		} catch (e) {
			error = e instanceof Error ? e.message : '재시도 실패';
		}
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
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function getStatusBadge(status: string): { class: string; text: string } {
		switch (status) {
			case 'pending':
				return { class: 'bg-muted text-foreground', text: '대기' };
			case 'picked':
				return { class: 'bg-warning-light text-warning-foreground', text: '픽업됨' };
			case 'processing':
				return { class: 'bg-primary-light text-primary', text: '처리중' };
			case 'completed':
				return { class: 'bg-success-light text-success', text: '완료' };
			case 'failed':
				return { class: 'bg-error-light text-error', text: '실패' };
			default:
				return { class: 'bg-muted text-foreground', text: status };
		}
	}

	function getUrlTypeLabel(type: string): string {
		switch (type) {
			case 'instagram': return 'Instagram';
			case 'naver_blog': return '네이버 블로그';
			case 'naver_form': return '네이버 폼';
			case 'google_form': return 'Google Form';
			case 'other': return '기타';
			default: return type;
		}
	}

	onMount(() => {
		fetchRequests();
	});
</script>

<div class="mx-auto max-w-7xl space-y-4">
	<!-- 필터 -->
	<div class="card mb-6">
		<div class="flex flex-wrap gap-4 items-center">
			<div>
				<label for="urlType" class="block text-sm font-medium text-foreground mb-1">URL 타입</label>
				<select
					id="urlType"
					bind:value={urlType}
					onchange={handleFilterChange}
					class="input input-sm w-40"
				>
					<option value="">전체</option>
					<option value="instagram">Instagram</option>
					<option value="naver_blog">네이버 블로그</option>
					<option value="naver_form">네이버 폼</option>
					<option value="google_form">Google Form</option>
					<option value="other">기타</option>
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
					<option value="picked">픽업됨</option>
					<option value="processing">처리중</option>
					<option value="completed">완료</option>
					<option value="failed">실패</option>
				</select>
			</div>
		</div>
	</div>

	<!-- 요청 목록 -->
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if !requests || requests.length === 0}
		<div class="card text-center py-12">
			<p class="text-muted-foreground">요청 기록이 없습니다</p>
		</div>
	{:else}
		<div class="card overflow-hidden">
			<table class="min-w-full divide-y divide-border">
				<thead class="bg-background">
					<tr>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">ID</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">URL</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">타입</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">상태</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">요청 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">처리 시간</th>
						<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">액션</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-border">
					{#each requests as req}
						{@const badge = getStatusBadge(req.status)}
						<tr class="hover:bg-muted">
							<td class="px-4 py-3 text-sm text-muted-foreground">
								{req.id}
							</td>
							<td class="px-4 py-3 text-sm text-foreground max-w-xs truncate" title={req.url}>
								{req.url}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">
								{getUrlTypeLabel(req.url_type)}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {badge.class}">
									{badge.text}
								</span>
								{#if req.error_message}
									<span class="ml-2 text-xs text-error" title={req.error_message}>
										{req.error_message.substring(0, 20)}...
									</span>
								{/if}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">
								{formatDateTime(req.requested_at)}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">
								{formatDateTime(req.processed_at)}
							</td>
							<td class="px-4 py-3 text-center">
								{#if req.status === 'failed'}
									<Button variant="secondary" size="xs" onclick={() => handleRetry(req.id)}
									>
										재시도
									</Button>
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
					onclick={() => { page = Math.max(1, page - 1); fetchRequests(); }}
					disabled={page === 1}
					class="btn btn-secondary btn-sm"
				>
					이전
				</button>
				<span class="text-sm text-muted-foreground">
					{page} / {totalPages}
				</span>
				<button
					onclick={() => { page = Math.min(totalPages, page + 1); fetchRequests(); }}
					disabled={page === totalPages}
					class="btn btn-secondary btn-sm"
				>
					다음
				</button>
			</div>
		{/if}
	{/if}
</div>
