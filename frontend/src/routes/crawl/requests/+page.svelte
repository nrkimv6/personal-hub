<script lang="ts">
	import { onMount } from 'svelte';
	import { crawlApiV2 } from '$lib/api';
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
			const response = await crawlApiV2.getRequests({
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
			await crawlApiV2.retryRequest(requestId);
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
				return { class: 'bg-gray-100 text-gray-800', text: '대기' };
			case 'picked':
				return { class: 'bg-yellow-100 text-yellow-800', text: '픽업됨' };
			case 'processing':
				return { class: 'bg-blue-100 text-blue-800', text: '처리중' };
			case 'completed':
				return { class: 'bg-green-100 text-green-800', text: '완료' };
			case 'failed':
				return { class: 'bg-red-100 text-red-800', text: '실패' };
			default:
				return { class: 'bg-gray-100 text-gray-800', text: status };
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

<div class="p-6 max-w-7xl mx-auto">
	<div class="mb-6">
		<h2 class="text-2xl font-bold text-gray-900">단건 크롤링 요청</h2>
		<p class="text-sm text-gray-500 mt-1">개별 URL 크롤링 요청 목록</p>
	</div>

	<!-- 필터 -->
	<div class="card mb-6">
		<div class="flex flex-wrap gap-4 items-center">
			<div>
				<label for="urlType" class="block text-sm font-medium text-gray-700 mb-1">URL 타입</label>
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
				<label for="status" class="block text-sm font-medium text-gray-700 mb-1">상태</label>
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
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if !requests || requests.length === 0}
		<div class="card text-center py-12">
			<p class="text-gray-500">요청 기록이 없습니다</p>
		</div>
	{:else}
		<div class="card overflow-hidden">
			<table class="min-w-full divide-y divide-gray-200">
				<thead class="bg-gray-50">
					<tr>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">URL</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">타입</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">요청 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">처리 시간</th>
						<th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">액션</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-gray-200">
					{#each requests as req}
						{@const badge = getStatusBadge(req.status)}
						<tr class="hover:bg-gray-50">
							<td class="px-4 py-3 text-sm text-gray-500">
								{req.id}
							</td>
							<td class="px-4 py-3 text-sm text-gray-900 max-w-xs truncate" title={req.url}>
								{req.url}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600">
								{getUrlTypeLabel(req.url_type)}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {badge.class}">
									{badge.text}
								</span>
								{#if req.error_message}
									<span class="ml-2 text-xs text-red-500" title={req.error_message}>
										{req.error_message.substring(0, 20)}...
									</span>
								{/if}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600">
								{formatDateTime(req.requested_at)}
							</td>
							<td class="px-4 py-3 text-sm text-gray-600">
								{formatDateTime(req.processed_at)}
							</td>
							<td class="px-4 py-3 text-center">
								{#if req.status === 'failed'}
									<button
										onclick={() => handleRetry(req.id)}
										class="btn btn-secondary btn-xs"
									>
										재시도
									</button>
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
				<span class="text-sm text-gray-600">
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
