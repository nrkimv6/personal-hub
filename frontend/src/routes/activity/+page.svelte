<script lang="ts">
	import { onMount } from 'svelte';

	// 타입 정의
	interface WorkerStatus {
		is_running: boolean;
		last_activity: string | null;
		pending_requests: number;
		processing_requests: number;
		recent_runs: number;
	}

	interface Center {
		id: number;
		name: string;
		center_type: string;
		region: string;
		district: string | null;
		is_active: boolean;
		last_crawled_at: string | null;
		crawl_method: string;
		created_at: string;
	}

	interface CrawlRequest {
		id: number;
		url: string;
		status: string;
		requested_at: string;
		processed_at: string | null;
		error_message: string | null;
	}

	// API 함수
	const API_BASE = '/api/activity';

	async function apiRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
		const response = await fetch(`${API_BASE}${endpoint}`, {
			headers: { 'Content-Type': 'application/json', ...options.headers },
			...options
		});
		if (!response.ok) {
			const error = await response.json().catch(() => ({ detail: response.statusText }));
			throw new Error(error.detail || '요청 실패');
		}
		return response.json();
	}

	// 상태
	let workerStatus: WorkerStatus | null = $state(null);
	let centers: Center[] = $state([]);
	let requests: CrawlRequest[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	// 워커 상태 로드
	async function loadWorkerStatus() {
		try {
			workerStatus = await apiRequest<WorkerStatus>('/worker/status');
		} catch (e) {
			console.error('워커 상태 로드 실패:', e);
		}
	}

	// 센터 목록 로드
	async function loadCenters() {
		try {
			const response = await apiRequest<{ items: Center[]; total: number }>('/centers/?limit=50');
			centers = response.items;
		} catch (e) {
			console.error('센터 목록 로드 실패:', e);
		}
	}

	// 요청 목록 로드
	async function loadRequests() {
		try {
			requests = await apiRequest<CrawlRequest[]>('/worker/requests?limit=10');
		} catch (e) {
			console.error('요청 목록 로드 실패:', e);
		}
	}

	// 크롤링 요청 생성
	async function requestCrawl(centerId: number) {
		try {
			await apiRequest('/worker/request', {
				method: 'POST',
				body: JSON.stringify({ center_id: centerId })
			});
			await loadRequests();
			await loadWorkerStatus();
		} catch (e) {
			error = e instanceof Error ? e.message : '요청 실패';
		}
	}

	function formatDate(dateStr: string | null): string {
		if (!dateStr) return '-';
		return new Date(dateStr).toLocaleString('ko-KR', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function getStatusBadge(status: string): { bg: string; text: string; label: string } {
		switch (status) {
			case 'pending':
				return { bg: 'bg-yellow-100', text: 'text-yellow-700', label: '대기' };
			case 'picked':
			case 'processing':
				return { bg: 'bg-blue-100', text: 'text-blue-700', label: '처리중' };
			case 'completed':
				return { bg: 'bg-green-100', text: 'text-green-700', label: '완료' };
			case 'failed':
				return { bg: 'bg-red-100', text: 'text-red-700', label: '실패' };
			default:
				return { bg: 'bg-gray-100', text: 'text-gray-700', label: status };
		}
	}

	function getCenterTypeName(type: string): string {
		const types: Record<string, string> = {
			culture: '문화센터',
			sports: '체육센터',
			youth: '청소년센터',
			welfare: '복지관'
		};
		return types[type] || type;
	}

	onMount(async () => {
		loading = true;
		await Promise.all([loadWorkerStatus(), loadCenters(), loadRequests()]);
		loading = false;
	});
</script>

<svelte:head>
	<title>문화/체육센터 | Monitor Page</title>
</svelte:head>

<div class="container mx-auto p-4">
	<h1 class="mb-6 text-2xl font-bold">문화/체육센터 강좌</h1>

	{#if error}
		<div class="mb-6 rounded-lg bg-red-100 p-4 text-red-700">{error}</div>
	{/if}

	{#if loading}
		<div class="text-gray-500">로딩 중...</div>
	{:else}
		<div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
			<!-- 워커 상태 카드 -->
			<div class="rounded-lg bg-white p-4 shadow">
				<h2 class="mb-4 text-lg font-semibold">워커 상태</h2>

				{#if workerStatus}
					<div class="space-y-3">
						<div class="flex items-center justify-between">
							<span class="text-gray-600">상태</span>
							{#if workerStatus.is_running}
								<span class="rounded bg-green-100 px-2 py-1 text-sm text-green-700">실행 중</span>
							{:else}
								<span class="rounded bg-gray-100 px-2 py-1 text-sm text-gray-600">대기</span>
							{/if}
						</div>
						<div class="flex items-center justify-between">
							<span class="text-gray-600">대기 요청</span>
							<span class="font-medium">{workerStatus.pending_requests}</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-gray-600">처리 중</span>
							<span class="font-medium">{workerStatus.processing_requests}</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-gray-600">24시간 크롤링</span>
							<span class="font-medium">{workerStatus.recent_runs}회</span>
						</div>
						{#if workerStatus.last_activity}
							<div class="flex items-center justify-between">
								<span class="text-gray-600">마지막 활동</span>
								<span class="text-sm">{formatDate(workerStatus.last_activity)}</span>
							</div>
						{/if}
					</div>
				{:else}
					<div class="text-gray-500">워커 상태를 가져올 수 없습니다.</div>
				{/if}
			</div>

			<!-- 최근 요청 카드 -->
			<div class="rounded-lg bg-white p-4 shadow lg:col-span-2">
				<h2 class="mb-4 text-lg font-semibold">최근 크롤링 요청</h2>

				{#if requests.length === 0}
					<div class="text-gray-500">요청 내역이 없습니다.</div>
				{:else}
					<div class="overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b text-left text-gray-500">
									<th class="pb-2">ID</th>
									<th class="pb-2">URL</th>
									<th class="pb-2">상태</th>
									<th class="pb-2">요청시간</th>
								</tr>
							</thead>
							<tbody>
								{#each requests as req}
									{@const badge = getStatusBadge(req.status)}
									<tr class="border-b">
										<td class="py-2">{req.id}</td>
										<td class="py-2">
											<span class="max-w-48 truncate" title={req.url}>{req.url}</span>
										</td>
										<td class="py-2">
											<span class="rounded px-2 py-0.5 {badge.bg} {badge.text}">
												{badge.label}
											</span>
										</td>
										<td class="py-2 text-gray-500">{formatDate(req.requested_at)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>

		<!-- 센터 목록 -->
		<div class="mt-6 rounded-lg bg-white p-4 shadow">
			<h2 class="mb-4 text-lg font-semibold">등록된 센터 ({centers.length})</h2>

			{#if centers.length === 0}
				<div class="text-gray-500">등록된 센터가 없습니다.</div>
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b text-left text-gray-500">
								<th class="pb-2">ID</th>
								<th class="pb-2">이름</th>
								<th class="pb-2">유형</th>
								<th class="pb-2">지역</th>
								<th class="pb-2">크롤링 방식</th>
								<th class="pb-2">마지막 크롤링</th>
								<th class="pb-2">상태</th>
								<th class="pb-2">작업</th>
							</tr>
						</thead>
						<tbody>
							{#each centers as center}
								<tr class="border-b hover:bg-gray-50">
									<td class="py-2">{center.id}</td>
									<td class="py-2 font-medium">{center.name}</td>
									<td class="py-2">{getCenterTypeName(center.center_type)}</td>
									<td class="py-2">
										{center.region}
										{#if center.district}
											<span class="text-gray-400">{center.district}</span>
										{/if}
									</td>
									<td class="py-2">{center.crawl_method}</td>
									<td class="py-2 text-gray-500">{formatDate(center.last_crawled_at)}</td>
									<td class="py-2">
										{#if center.is_active}
											<span class="rounded bg-green-100 px-2 py-0.5 text-green-700">활성</span>
										{:else}
											<span class="rounded bg-gray-100 px-2 py-0.5 text-gray-600">비활성</span>
										{/if}
									</td>
									<td class="py-2">
										<button
											onclick={() => requestCrawl(center.id)}
											disabled={!center.is_active}
											class="rounded bg-blue-500 px-3 py-1 text-white hover:bg-blue-600 disabled:opacity-50"
										>
											크롤링
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	{/if}
</div>
