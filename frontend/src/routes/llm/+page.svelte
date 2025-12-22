<script lang="ts">
	import { onMount } from 'svelte';
	import { llmApi, type LLMRequest, type LLMStats, type LLMWorkerStatus, type LLMHistoryStats } from '$lib/api';

	// 상태
	let requests: LLMRequest[] = [];
	let stats: LLMStats | null = null;
	let workerStatus: LLMWorkerStatus | null = null;
	let historyStats: LLMHistoryStats | null = null;

	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let page = 1;
	let pageSize = 20;
	let total = 0;
	let pages = 0;

	// 필터
	let filterStatus = '';
	let filterCallerType = '';
	let filterRequestedBy = '';

	// 선택
	let selectedIds: number[] = [];
	let selectAll = false;

	// 탭
	type Tab = 'queue' | 'history' | 'stats';
	let activeTab: Tab = 'queue';

	// 모달
	let selectedRequest: LLMRequest | null = null;
	let showModal = false;

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const [listRes, statsRes, workerRes] = await Promise.all([
				llmApi.list({
					status: filterStatus || undefined,
					caller_type: filterCallerType || undefined,
					requested_by: filterRequestedBy || undefined,
					page,
					page_size: pageSize
				}),
				llmApi.getStats(),
				llmApi.getWorkerStatus()
			]);

			requests = listRes.items;
			total = listRes.total;
			pages = listRes.pages;
			stats = statsRes;
			workerStatus = workerRes;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function fetchHistoryStats() {
		try {
			historyStats = await llmApi.getHistoryStats();
		} catch (e) {
			console.error('이력 통계 로드 실패:', e);
		}
	}

	function handleFilter() {
		page = 1;
		selectedIds = [];
		selectAll = false;
		fetchData();
	}

	function clearFilters() {
		filterStatus = '';
		filterCallerType = '';
		filterRequestedBy = '';
		handleFilter();
	}

	function prevPage() {
		if (page > 1) {
			page--;
			fetchData();
		}
	}

	function nextPage() {
		if (page < pages) {
			page++;
			fetchData();
		}
	}

	function toggleSelectAll() {
		selectAll = !selectAll;
		if (selectAll) {
			selectedIds = requests.map(r => r.id);
		} else {
			selectedIds = [];
		}
	}

	function toggleSelect(id: number) {
		if (selectedIds.includes(id)) {
			selectedIds = selectedIds.filter(i => i !== id);
		} else {
			selectedIds = [...selectedIds, id];
		}
	}

	async function cancelRequest(id: number) {
		try {
			await llmApi.cancel(id);
			await fetchData();
		} catch (e) {
			alert('취소 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function retryRequest(id: number) {
		try {
			await llmApi.retry(id);
			await fetchData();
		} catch (e) {
			alert('재시도 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function deleteRequest(id: number) {
		if (!confirm('이 요청을 삭제하시겠습니까?')) return;
		try {
			await llmApi.delete(id);
			await fetchData();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function batchRetry() {
		if (selectedIds.length === 0) return;
		try {
			const result = await llmApi.batchRetry(selectedIds);
			alert(`재시도 완료: 성공 ${result.success}개, 스킵 ${result.skipped}개`);
			selectedIds = [];
			selectAll = false;
			await fetchData();
		} catch (e) {
			alert('일괄 재시도 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function batchDelete() {
		if (selectedIds.length === 0) return;
		if (!confirm(`선택한 ${selectedIds.length}개 요청을 삭제하시겠습니까?`)) return;
		try {
			const result = await llmApi.batchDelete(selectedIds);
			alert(`삭제 완료: ${result.deleted}개`);
			selectedIds = [];
			selectAll = false;
			await fetchData();
		} catch (e) {
			alert('일괄 삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	function openModal(request: LLMRequest) {
		selectedRequest = request;
		showModal = true;
	}

	function closeModal() {
		showModal = false;
		selectedRequest = null;
	}

	function formatDateTime(isoString: string | null | undefined): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function getStatusColor(status: string): string {
		switch (status) {
			case 'pending': return 'bg-yellow-100 text-yellow-800';
			case 'processing': return 'bg-blue-100 text-blue-800';
			case 'completed': return 'bg-green-100 text-green-800';
			case 'failed': return 'bg-red-100 text-red-800';
			case 'cancelled': return 'bg-gray-100 text-gray-800';
			default: return 'bg-gray-100 text-gray-800';
		}
	}

	function getStatusLabel(status: string): string {
		switch (status) {
			case 'pending': return '대기';
			case 'processing': return '처리중';
			case 'completed': return '완료';
			case 'failed': return '실패';
			case 'cancelled': return '취소';
			default: return status;
		}
	}

	function switchTab(tab: Tab) {
		activeTab = tab;
		if (tab === 'history' && !historyStats) {
			fetchHistoryStats();
		}
	}

	onMount(() => {
		fetchData();
	});
</script>

<div class="p-6">
	<!-- 헤더 -->
	<div class="mb-6 flex justify-between items-center">
		<h2 class="text-2xl font-bold text-gray-900">LLM 요청 관리</h2>
		<button onclick={() => fetchData()} class="btn btn-secondary btn-sm">
			새로고침
		</button>
	</div>

	<!-- 워커 상태 및 통계 카드 -->
	{#if stats || workerStatus}
		<div class="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
			<!-- 워커 상태 -->
			<div class="card p-4">
				<div class="text-sm text-gray-500">워커 상태</div>
				<div class="text-lg font-bold {workerStatus?.status === 'healthy' ? 'text-green-600' : workerStatus?.status === 'no_worker' ? 'text-gray-500' : 'text-red-600'}">
					{workerStatus?.status === 'healthy' ? '정상' : workerStatus?.status === 'no_worker' ? '없음' : '비정상'}
				</div>
				{#if workerStatus?.state}
					<div class="text-xs text-gray-400">{workerStatus.state}</div>
				{/if}
			</div>

			<!-- 통계 카드들 -->
			{#if stats}
				<div class="card p-4">
					<div class="text-sm text-gray-500">전체</div>
					<div class="text-2xl font-bold text-gray-900">{stats.total}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">대기중</div>
					<div class="text-2xl font-bold text-yellow-600">{stats.pending}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">처리중</div>
					<div class="text-2xl font-bold text-blue-600">{stats.processing}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">완료</div>
					<div class="text-2xl font-bold text-green-600">{stats.completed}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">실패</div>
					<div class="text-2xl font-bold text-red-600">{stats.failed}</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- 탭 -->
	<div class="mb-4 border-b border-gray-200">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('queue')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'queue' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				대기열
			</button>
			<button
				onclick={() => switchTab('history')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'history' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				이력 통계
			</button>
		</nav>
	</div>

	{#if activeTab === 'queue'}
		<!-- 필터 -->
		<div class="mb-4 flex flex-wrap gap-2 items-center">
			<select bind:value={filterStatus} class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm">
				<option value="">전체 상태</option>
				<option value="pending">대기</option>
				<option value="processing">처리중</option>
				<option value="completed">완료</option>
				<option value="failed">실패</option>
				<option value="cancelled">취소</option>
			</select>
			<select bind:value={filterCallerType} class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm">
				<option value="">전체 타입</option>
				<option value="instagram">Instagram</option>
			</select>
			<input
				type="text"
				placeholder="요청자"
				bind:value={filterRequestedBy}
				class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
			/>
			<button onclick={handleFilter} class="btn btn-primary btn-sm">필터</button>
			<button onclick={clearFilters} class="btn btn-secondary btn-sm">초기화</button>
		</div>

		<!-- 일괄 작업 버튼 -->
		{#if selectedIds.length > 0}
			<div class="mb-4 flex gap-2 items-center">
				<span class="text-sm text-gray-600">{selectedIds.length}개 선택</span>
				<button onclick={batchRetry} class="btn btn-secondary btn-sm">일괄 재시도</button>
				<button onclick={batchDelete} class="btn btn-danger btn-sm">일괄 삭제</button>
			</div>
		{/if}

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
		{:else if requests.length === 0}
			<div class="text-center py-12 text-gray-500">
				<p class="text-lg">요청이 없습니다</p>
			</div>
		{:else}
			<!-- 요청 목록 테이블 -->
			<div class="bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
				<table class="w-full">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-4 py-3 text-left">
								<input
									type="checkbox"
									checked={selectAll}
									onchange={toggleSelectAll}
									class="rounded"
								/>
							</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">타입</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">호출자 ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">요청자</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">요청시간</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each requests as request (request.id)}
							<tr
								class="hover:bg-gray-50 cursor-pointer"
								onclick={() => openModal(request)}
							>
								<td class="px-4 py-3" onclick={(e) => e.stopPropagation()}>
									<input
										type="checkbox"
										checked={selectedIds.includes(request.id)}
										onchange={() => toggleSelect(request.id)}
										class="rounded"
									/>
								</td>
								<td class="px-4 py-3 text-sm text-gray-900">{request.id}</td>
								<td class="px-4 py-3 text-sm text-gray-600">{request.caller_type}</td>
								<td class="px-4 py-3 text-sm text-gray-600">{request.caller_id}</td>
								<td class="px-4 py-3 text-sm text-gray-600">{request.requested_by || '-'}</td>
								<td class="px-4 py-3">
									<span class="px-2 py-1 text-xs rounded-full {getStatusColor(request.status)}">
										{getStatusLabel(request.status)}
									</span>
								</td>
								<td class="px-4 py-3 text-sm text-gray-500">{formatDateTime(request.requested_at)}</td>
								<td class="px-4 py-3" onclick={(e) => e.stopPropagation()}>
									<div class="flex gap-1">
										{#if request.status === 'pending'}
											<button
												onclick={() => cancelRequest(request.id)}
												class="text-yellow-600 hover:text-yellow-800 text-sm"
											>
												취소
											</button>
										{/if}
										{#if request.status === 'failed'}
											<button
												onclick={() => retryRequest(request.id)}
												class="text-blue-600 hover:text-blue-800 text-sm"
											>
												재시도
											</button>
										{/if}
										<button
											onclick={() => deleteRequest(request.id)}
											class="text-red-600 hover:text-red-800 text-sm"
										>
											삭제
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			<div class="flex justify-between items-center">
				<span class="text-sm text-gray-500">
					전체 {total}개 중 {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)}
				</span>
				<div class="flex gap-2">
					<button
						onclick={prevPage}
						disabled={page === 1}
						class="btn btn-secondary btn-sm disabled:opacity-50"
					>
						이전
					</button>
					<span class="px-3 py-1.5 text-sm">{page} / {pages}</span>
					<button
						onclick={nextPage}
						disabled={page >= pages}
						class="btn btn-secondary btn-sm disabled:opacity-50"
					>
						다음
					</button>
				</div>
			</div>
		{/if}
	{:else if activeTab === 'history'}
		<!-- 이력 통계 탭 -->
		{#if historyStats}
			<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
				<div class="card p-4">
					<div class="text-sm text-gray-500">총 요청 (7일)</div>
					<div class="text-2xl font-bold text-gray-900">{historyStats.summary.total}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">성공률</div>
					<div class="text-2xl font-bold text-green-600">{historyStats.summary.success_rate}%</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">완료</div>
					<div class="text-2xl font-bold text-green-600">{historyStats.summary.completed}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">평균 처리 시간</div>
					<div class="text-2xl font-bold text-blue-600">{historyStats.summary.avg_processing_time_seconds}s</div>
				</div>
			</div>

			<!-- 일별 데이터 테이블 -->
			{#if historyStats.data.length > 0}
				<div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
					<table class="w-full">
						<thead class="bg-gray-50 border-b border-gray-200">
							<tr>
								<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">날짜</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">전체</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">완료</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">실패</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">대기</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-gray-200">
							{#each historyStats.data as day}
								<tr>
									<td class="px-4 py-3 text-sm text-gray-900">{day.date}</td>
									<td class="px-4 py-3 text-sm text-gray-600">{day.total}</td>
									<td class="px-4 py-3 text-sm text-green-600">{day.completed}</td>
									<td class="px-4 py-3 text-sm text-red-600">{day.failed}</td>
									<td class="px-4 py-3 text-sm text-yellow-600">{day.pending}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<div class="text-center py-12 text-gray-500">
					<p>기간 내 데이터가 없습니다</p>
				</div>
			{/if}
		{:else}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{/if}
	{/if}
</div>

<!-- 상세 모달 -->
{#if showModal && selectedRequest}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeModal}
		onkeydown={(e) => e.key === 'Escape' && closeModal()}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<div>
						<h3 class="text-lg font-bold text-gray-900">요청 상세 #{selectedRequest.id}</h3>
						<span class="px-2 py-1 text-xs rounded-full {getStatusColor(selectedRequest.status)}">
							{getStatusLabel(selectedRequest.status)}
						</span>
					</div>
					<button onclick={closeModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="grid grid-cols-2 gap-4 text-sm mb-4">
					<div>
						<span class="text-gray-500">타입:</span>
						<span class="ml-1">{selectedRequest.caller_type}</span>
					</div>
					<div>
						<span class="text-gray-500">호출자 ID:</span>
						<span class="ml-1">{selectedRequest.caller_id}</span>
					</div>
					<div>
						<span class="text-gray-500">요청자:</span>
						<span class="ml-1">{selectedRequest.requested_by || '-'}</span>
					</div>
					<div>
						<span class="text-gray-500">출처:</span>
						<span class="ml-1">{selectedRequest.request_source || '-'}</span>
					</div>
					<div>
						<span class="text-gray-500">요청 시간:</span>
						<span class="ml-1">{formatDateTime(selectedRequest.requested_at)}</span>
					</div>
					<div>
						<span class="text-gray-500">처리 시간:</span>
						<span class="ml-1">{formatDateTime(selectedRequest.processed_at)}</span>
					</div>
					<div>
						<span class="text-gray-500">재시도 횟수:</span>
						<span class="ml-1">{selectedRequest.retry_count}</span>
					</div>
				</div>

				{#if selectedRequest.error_message}
					<div class="mb-4 p-3 bg-red-50 rounded-lg">
						<div class="text-sm font-medium text-red-800 mb-1">에러 메시지</div>
						<p class="text-sm text-red-700 whitespace-pre-wrap">{selectedRequest.error_message}</p>
					</div>
				{/if}

				{#if selectedRequest.result}
					<div class="mb-4 p-3 bg-gray-50 rounded-lg">
						<div class="text-sm font-medium text-gray-800 mb-1">결과</div>
						<pre class="text-sm text-gray-700 whitespace-pre-wrap overflow-auto max-h-64">{JSON.stringify(selectedRequest.result, null, 2)}</pre>
					</div>
				{/if}

				<div class="flex gap-2 flex-wrap">
					{#if selectedRequest.status === 'pending'}
						<button
							onclick={() => { cancelRequest(selectedRequest!.id); closeModal(); }}
							class="btn btn-secondary btn-sm"
						>
							취소
						</button>
					{/if}
					{#if selectedRequest.status === 'failed'}
						<button
							onclick={() => { retryRequest(selectedRequest!.id); closeModal(); }}
							class="btn btn-primary btn-sm"
						>
							재시도
						</button>
					{/if}
					<button
						onclick={() => { deleteRequest(selectedRequest!.id); closeModal(); }}
						class="btn btn-danger btn-sm"
					>
						삭제
					</button>
					<button onclick={closeModal} class="btn btn-secondary btn-sm">닫기</button>
				</div>
			</div>
		</div>
	</div>
{/if}
