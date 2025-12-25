<script lang="ts">
	/**
	 * 크롤링 이력 탭 컴포넌트
	 */
	import { onMount } from 'svelte';
	import { crawlApi, type UniversalCrawlRequest, type CrawledPage, type CrawlRequestListParams } from '$lib/api';
	import { toast } from '$lib/stores/toast';
	import { isAdmin } from '$lib/stores/auth';

	// Props
	interface Props {
		currentPage?: number;
		pageSize?: number;
		onTotalChange?: (total: number) => void;
	}

	let { currentPage = $bindable(1), pageSize = 20, onTotalChange }: Props = $props();

	// 상태
	let requests: UniversalCrawlRequest[] = $state([]);
	let total = $state(0);
	let totalPages = $state(1);
	let loading = $state(true);
	let error: string | null = $state(null);

	// 필터
	let filterStatus: string | null = $state(null);
	let filterAnalysis: string | null = $state(null);

	// AI 분석 중인 페이지 ID 세트
	let analyzingPages: Set<number> = $state(new Set());

	// 크롤링 요청 모달
	let showAddModal = $state(false);
	let newUrl = $state('');
	let submitting = $state(false);

	// 상세 보기 모달
	let showDetailModal = $state(false);
	let selectedRequest: UniversalCrawlRequest | null = $state(null);
	let selectedPage: CrawledPage | null = $state(null);
	let loadingDetail = $state(false);

	// total 변경 시 부모에 알림
	$effect(() => {
		onTotalChange?.(total);
	});

	// currentPage 변경 시 재조회
	$effect(() => {
		if (currentPage) {
			fetchRequests();
		}
	});

	export async function fetchRequests() {
		loading = true;
		try {
			const params: CrawlRequestListParams = {
				page: currentPage,
				page_size: pageSize
			};
			if (filterStatus) params.status = filterStatus;
			if (filterAnalysis) params.analysis_status = filterAnalysis;

			const response = await crawlApi.listRequests(params);
			requests = response.items;
			total = response.total;
			totalPages = response.total_pages || Math.ceil(total / pageSize);
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function handleAddRequest() {
		if (!newUrl.trim()) {
			toast.warning('URL을 입력해주세요.');
			return;
		}

		submitting = true;
		try {
			const response = await crawlApi.createRequest({
				url: newUrl.trim(),
				auto_analyze: true,
				priority: 0
			});

			if (response.success) {
				toast.success(`크롤링 요청 등록 완료 (${response.url_type})`);
				newUrl = '';
				showAddModal = false;
				await fetchRequests();
			}
		} catch (e) {
			const message = e instanceof Error ? e.message : '알 수 없는 오류';
			if (message.includes('Instagram')) {
				toast.warning('Instagram URL은 Instagram 크롤러를 사용하세요.');
			} else {
				toast.error(`오류: ${message}`);
			}
		} finally {
			submitting = false;
		}
	}

	async function handleRetry(requestId: number) {
		try {
			await crawlApi.retryRequest(requestId);
			toast.success('재시도 요청 완료');
			await fetchRequests();
		} catch (e) {
			toast.error('재시도 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function openDetail(request: UniversalCrawlRequest) {
		selectedRequest = request;
		selectedPage = null;
		showDetailModal = true;

		if (request.crawled_page_id) {
			loadingDetail = true;
			try {
				selectedPage = await crawlApi.getPage(request.crawled_page_id);
			} catch (e) {
				console.error('페이지 로드 실패:', e);
			} finally {
				loadingDetail = false;
			}
		}
	}

	function getStatusBadge(status: string) {
		switch (status) {
			case 'pending': return 'bg-yellow-100 text-yellow-800';
			case 'processing': return 'bg-blue-100 text-blue-800';
			case 'completed': return 'bg-green-100 text-green-800';
			case 'failed': return 'bg-red-100 text-red-800';
			default: return 'bg-gray-100 text-gray-800';
		}
	}

	function getStatusText(status: string) {
		switch (status) {
			case 'pending': return '대기';
			case 'processing': return '처리 중';
			case 'completed': return '완료';
			case 'failed': return '실패';
			default: return status;
		}
	}

	function getUrlTypeBadge(urlType: string) {
		switch (urlType) {
			case 'google_form': return 'bg-blue-100 text-blue-700';
			case 'naver_form': return 'bg-green-100 text-green-700';
			case 'naver_blog': return 'bg-emerald-100 text-emerald-700';
			default: return 'bg-gray-100 text-gray-600';
		}
	}

	function getAnalysisResult(req: UniversalCrawlRequest) {
		if (!req.crawled_page) return { text: '-', badge: 'text-gray-400' };
		if (req.crawled_page.is_event === null || req.crawled_page.is_event === undefined) {
			return { text: '미분석', badge: 'bg-gray-100 text-gray-600' };
		}
		if (req.crawled_page.is_event) {
			return { text: '이벤트', badge: 'bg-purple-100 text-purple-700' };
		}
		return { text: '미분류', badge: 'bg-yellow-100 text-yellow-700' };
	}

	function formatDate(dateStr: string) {
		const date = new Date(dateStr);
		return date.toLocaleString('ko-KR', {
			month: 'numeric',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function handleStatusFilter(status: string | null) {
		filterStatus = status;
		currentPage = 1;
		fetchRequests();
	}

	function handleAnalysisFilter(analysis: string | null) {
		filterAnalysis = analysis;
		currentPage = 1;
		fetchRequests();
	}

	// AI 분석 요청
	async function handleAnalyze(req: UniversalCrawlRequest) {
		if (!req.crawled_page_id) {
			toast.warning('크롤링이 완료되지 않은 페이지입니다.');
			return;
		}

		const pageId = req.crawled_page_id;
		analyzingPages = new Set([...analyzingPages, pageId]);

		try {
			const response = await crawlApi.analyzePage(pageId);
			if (response.success) {
				toast.success(response.message);
				// 목록 새로고침
				await fetchRequests();
			}
		} catch (e) {
			toast.error('AI 분석 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			const newSet = new Set(analyzingPages);
			newSet.delete(pageId);
			analyzingPages = newSet;
		}
	}

	// 페이지네이션
	function goToPage(page: number) {
		if (page >= 1 && page <= totalPages) {
			currentPage = page;
		}
	}

	// AI 분석 가능 여부 확인
	function canAnalyze(req: UniversalCrawlRequest): boolean {
		// 크롤링 완료 + 미분석 상태에서만 활성화
		if (req.status !== 'completed') return false;
		if (!req.crawled_page_id) return false;
		if (req.crawled_page?.is_event !== null && req.crawled_page?.is_event !== undefined) return false;
		return true;
	}

	// 외부에서 접근 가능한 함수들
	export function openAddModal() {
		showAddModal = true;
	}

	export function getTotal() {
		return total;
	}

	export function getLoading() {
		return loading;
	}

	export function getError() {
		return error;
	}

	export function getRequestsLength() {
		return requests.length;
	}

	onMount(() => {
		fetchRequests();
	});
</script>

<!-- 필터 -->
<div class="mb-4 space-y-2">
	<!-- 상태 필터 -->
	<div class="flex flex-wrap gap-2">
		<span class="text-sm text-gray-500 py-1.5">상태:</span>
		<button
			onclick={() => handleStatusFilter(null)}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === null
				? 'bg-gray-800 text-white'
				: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
		>
			전체
		</button>
		<button
			onclick={() => handleStatusFilter('pending')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'pending'
				? 'bg-yellow-600 text-white'
				: 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'}"
		>
			대기
		</button>
		<button
			onclick={() => handleStatusFilter('processing')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'processing'
				? 'bg-blue-600 text-white'
				: 'bg-blue-100 text-blue-700 hover:bg-blue-200'}"
		>
			처리 중
		</button>
		<button
			onclick={() => handleStatusFilter('completed')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'completed'
				? 'bg-green-600 text-white'
				: 'bg-green-100 text-green-700 hover:bg-green-200'}"
		>
			완료
		</button>
		<button
			onclick={() => handleStatusFilter('failed')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'failed'
				? 'bg-red-600 text-white'
				: 'bg-red-100 text-red-700 hover:bg-red-200'}"
		>
			실패
		</button>
	</div>
	<!-- 분석 상태 필터 -->
	<div class="flex flex-wrap gap-2">
		<span class="text-sm text-gray-500 py-1.5">분석:</span>
		<button
			onclick={() => handleAnalysisFilter(null)}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterAnalysis === null
				? 'bg-gray-800 text-white'
				: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
		>
			전체
		</button>
		<button
			onclick={() => handleAnalysisFilter('event')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterAnalysis === 'event'
				? 'bg-purple-600 text-white'
				: 'bg-purple-100 text-purple-700 hover:bg-purple-200'}"
		>
			이벤트
		</button>
		<button
			onclick={() => handleAnalysisFilter('uncategorized')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterAnalysis === 'uncategorized'
				? 'bg-orange-600 text-white'
				: 'bg-orange-100 text-orange-700 hover:bg-orange-200'}"
		>
			미분류
		</button>
		<button
			onclick={() => handleAnalysisFilter('unanalyzed')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterAnalysis === 'unanalyzed'
				? 'bg-gray-600 text-white'
				: 'bg-gray-200 text-gray-600 hover:bg-gray-300'}"
		>
			미분석
		</button>
	</div>
</div>

<!-- 목록 -->
{#if loading && requests.length === 0}
	<div class="flex justify-center items-center h-64">
		<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
	</div>
{:else if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
		{error}
	</div>
{:else if requests.length === 0}
	<div class="text-center py-12 text-gray-500">
		<p class="text-lg">크롤링 요청 이력이 없습니다</p>
		{#if $isAdmin}
			<button onclick={() => (showAddModal = true)} class="mt-4 btn btn-primary btn-sm">
				+ URL 크롤링 요청
			</button>
		{/if}
	</div>
{:else}
	<!-- 모바일 카드 뷰 -->
	<div class="md:hidden space-y-3">
		{#each requests as req}
			<div
				onclick={() => openDetail(req)}
				onkeydown={(e) => e.key === 'Enter' && openDetail(req)}
				role="button"
				tabindex="0"
				class="w-full text-left bg-white border rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
			>
				<div class="flex items-start justify-between gap-2 mb-2">
					<div class="flex gap-1">
						<span class="px-2 py-0.5 text-xs rounded-full {getStatusBadge(req.status)}">
							{getStatusText(req.status)}
						</span>
						<span class="px-2 py-0.5 text-xs rounded-full {getUrlTypeBadge(req.url_type)}">
							{req.url_type}
						</span>
					</div>
					{#if getAnalysisResult(req).text !== '-'}
						<span class="px-2 py-0.5 text-xs rounded-full {getAnalysisResult(req).badge}">{getAnalysisResult(req).text}</span>
					{/if}
				</div>
				<p class="text-sm text-gray-900 break-all line-clamp-2 mb-2">{req.url}</p>
				<div class="flex justify-between items-center text-xs text-gray-500">
					<span>{formatDate(req.requested_at)}</span>
					<div class="flex gap-2">
						{#if canAnalyze(req) && $isAdmin}
							<button
								onclick={(e) => {
									e.stopPropagation();
									handleAnalyze(req);
								}}
								disabled={Boolean(req.crawled_page_id && analyzingPages.has(req.crawled_page_id))}
								class="text-purple-600 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
							>
								{#if req.crawled_page_id && analyzingPages.has(req.crawled_page_id)}
									분석 중...
								{:else}
									AI 분석
								{/if}
							</button>
						{/if}
						{#if (req.status === 'failed' || req.status === 'completed') && $isAdmin}
							<button
								onclick={(e) => {
									e.stopPropagation();
									handleRetry(req.id);
								}}
								class="text-blue-600 hover:underline"
							>
								재시도
							</button>
						{/if}
					</div>
				</div>
			</div>
		{/each}
	</div>

	<!-- 데스크톱 테이블 뷰 -->
	<div class="hidden md:block overflow-x-auto">
		<table class="w-full">
			<thead>
				<tr class="border-b text-left text-sm text-gray-600">
					<th class="pb-3 font-medium">상태</th>
					<th class="pb-3 font-medium">타입</th>
					<th class="pb-3 font-medium">URL</th>
					<th class="pb-3 font-medium">분석결과</th>
					<th class="pb-3 font-medium">요청 시간</th>
					<th class="pb-3 font-medium">완료 시간</th>
					<th class="pb-3 font-medium"></th>
				</tr>
			</thead>
			<tbody>
				{#each requests as req}
					<tr class="border-b hover:bg-gray-50 cursor-pointer" onclick={() => openDetail(req)}>
						<td class="py-3">
							<span class="px-2 py-1 text-xs rounded-full {getStatusBadge(req.status)}">
								{getStatusText(req.status)}
							</span>
						</td>
						<td class="py-3">
							<span class="px-2 py-1 text-xs rounded-full {getUrlTypeBadge(req.url_type)}">
								{req.url_type}
							</span>
						</td>
						<td class="py-3 max-w-md">
							<span class="text-sm text-gray-700 break-all line-clamp-1">{req.url}</span>
						</td>
						<td class="py-3">
							{#if true}
								{@const result = getAnalysisResult(req)}
								{#if result.text === '-'}
									<span class="{result.badge}">{result.text}</span>
								{:else}
									<span class="px-2 py-1 text-xs rounded-full {result.badge}">{result.text}</span>
								{/if}
							{/if}
						</td>
						<td class="py-3 text-sm text-gray-600">{formatDate(req.requested_at)}</td>
						<td class="py-3 text-sm text-gray-600">
							{req.completed_at ? formatDate(req.completed_at) : '-'}
						</td>
						<td class="py-3">
							<div class="flex gap-2">
								{#if canAnalyze(req) && $isAdmin}
									<button
										onclick={(e) => {
											e.stopPropagation();
											handleAnalyze(req);
										}}
										disabled={Boolean(req.crawled_page_id && analyzingPages.has(req.crawled_page_id))}
										class="text-sm text-purple-600 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
									>
										{#if req.crawled_page_id && analyzingPages.has(req.crawled_page_id)}
											분석 중...
										{:else}
											AI 분석
										{/if}
									</button>
								{/if}
								{#if (req.status === 'failed' || req.status === 'completed') && $isAdmin}
									<button
										onclick={(e) => {
											e.stopPropagation();
											handleRetry(req.id);
										}}
										class="text-sm text-blue-600 hover:underline"
									>
										재시도
									</button>
								{/if}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<!-- 페이지네이션 -->
	{#if totalPages > 1}
		<div class="flex justify-between items-center mt-6 pt-4 border-t">
			<span class="text-sm text-gray-500">
				전체 {total}건 중 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)}
			</span>
			<div class="flex gap-2 items-center">
				<button
					onclick={() => goToPage(currentPage - 1)}
					disabled={currentPage === 1}
					class="px-3 py-1.5 text-sm rounded border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
				>
					이전
				</button>
				<span class="text-sm text-gray-600">
					{currentPage} / {totalPages}
				</span>
				<button
					onclick={() => goToPage(currentPage + 1)}
					disabled={currentPage >= totalPages}
					class="px-3 py-1.5 text-sm rounded border disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
				>
					다음
				</button>
			</div>
		</div>
	{/if}
{/if}

<!-- 크롤링 요청 모달 -->
{#if showAddModal}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={() => (showAddModal = false)}
		onkeydown={(e) => e.key === 'Escape' && (showAddModal = false)}
		role="dialog"
		tabindex="-1"
	>
		<div class="bg-white rounded-xl w-full max-w-lg p-6" onclick={(e) => e.stopPropagation()}>
			<div class="flex justify-between items-center mb-4">
				<h3 class="text-lg font-bold">URL 크롤링 요청</h3>
				<button onclick={() => (showAddModal = false)} class="text-gray-400 hover:text-gray-600 text-2xl">
					&times;
				</button>
			</div>

			<div class="space-y-4">
				<div>
					<label for="crawl-url" class="block text-sm font-medium text-gray-700 mb-1">URL</label>
					<input
						id="crawl-url"
						type="url"
						bind:value={newUrl}
						placeholder="https://forms.gle/... 또는 https://blog.naver.com/..."
						class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						onkeydown={(e) => e.key === 'Enter' && handleAddRequest()}
					/>
					<p class="mt-1 text-xs text-gray-500">
						구글폼, 네이버폼, 네이버 블로그 등 지원
					</p>
				</div>
			</div>

			<div class="mt-6 flex gap-2 justify-end">
				<button onclick={() => (showAddModal = false)} class="btn btn-secondary btn-sm">취소</button>
				<button onclick={handleAddRequest} disabled={submitting} class="btn btn-primary btn-sm disabled:opacity-50">
					{#if submitting}
						<span class="flex items-center gap-2">
							<span class="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
							요청 중...
						</span>
					{:else}
						요청
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- 크롤링 상세 모달 -->
{#if showDetailModal && selectedRequest}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={() => (showDetailModal = false)}
		onkeydown={(e) => e.key === 'Escape' && (showDetailModal = false)}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl w-full max-w-2xl max-h-[90vh] overflow-auto p-6"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex justify-between items-center mb-4">
				<div class="flex items-center gap-2">
					<h3 class="text-lg font-bold">크롤링 상세</h3>
					<span class="px-2 py-0.5 text-xs rounded-full {getStatusBadge(selectedRequest.status)}">
						{getStatusText(selectedRequest.status)}
					</span>
				</div>
				<button onclick={() => (showDetailModal = false)} class="text-gray-400 hover:text-gray-600 text-2xl">
					&times;
				</button>
			</div>

			<div class="space-y-4">
				<!-- 요청 정보 -->
				<div class="bg-gray-50 rounded-lg p-4">
					<h4 class="text-sm font-medium text-gray-700 mb-2">요청 정보</h4>
					<dl class="space-y-2 text-sm">
						<div class="flex">
							<dt class="w-24 text-gray-500">URL</dt>
							<dd class="flex-1 break-all">
								<a href={selectedRequest.url} target="_blank" class="text-blue-600 hover:underline">
									{selectedRequest.url}
								</a>
							</dd>
						</div>
						<div class="flex">
							<dt class="w-24 text-gray-500">타입</dt>
							<dd>{selectedRequest.url_type}</dd>
						</div>
						<div class="flex">
							<dt class="w-24 text-gray-500">요청 시간</dt>
							<dd>{new Date(selectedRequest.requested_at).toLocaleString('ko-KR')}</dd>
						</div>
						{#if selectedRequest.completed_at}
							<div class="flex">
								<dt class="w-24 text-gray-500">완료 시간</dt>
								<dd>{new Date(selectedRequest.completed_at).toLocaleString('ko-KR')}</dd>
							</div>
						{/if}
						{#if selectedRequest.error_message}
							<div class="flex">
								<dt class="w-24 text-gray-500">오류</dt>
								<dd class="text-red-600">{selectedRequest.error_message}</dd>
							</div>
						{/if}
					</dl>
				</div>

				<!-- 크롤링 결과 -->
				{#if loadingDetail}
					<div class="flex justify-center py-8">
						<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
					</div>
				{:else if selectedPage}
					<div class="bg-blue-50 rounded-lg p-4">
						<h4 class="text-sm font-medium text-gray-700 mb-2">크롤링 결과</h4>
						<dl class="space-y-2 text-sm">
							{#if selectedPage.title}
								<div class="flex">
									<dt class="w-24 text-gray-500">제목</dt>
									<dd class="font-medium">{selectedPage.title}</dd>
								</div>
							{/if}
							{#if selectedPage.description}
								<div class="flex">
									<dt class="w-24 text-gray-500">설명</dt>
									<dd class="text-gray-700">{selectedPage.description}</dd>
								</div>
							{/if}
							{#if selectedPage.extractor_used}
								<div class="flex">
									<dt class="w-24 text-gray-500">추출기</dt>
									<dd>{selectedPage.extractor_used}</dd>
								</div>
							{/if}
							{#if selectedPage.content}
								<div>
									<dt class="text-gray-500 mb-1">본문 (일부)</dt>
									<dd class="bg-white rounded p-2 text-xs text-gray-600 max-h-32 overflow-auto whitespace-pre-wrap">
										{selectedPage.content.substring(0, 500)}{selectedPage.content.length > 500 ? '...' : ''}
									</dd>
								</div>
							{/if}
						</dl>
					</div>

					<!-- AI 분석 결과 -->
					{#if selectedPage.is_event !== null && selectedPage.is_event !== undefined}
						<div class="bg-purple-50 rounded-lg p-4">
							<h4 class="text-sm font-medium text-gray-700 mb-2">AI 분석 결과</h4>
							<dl class="space-y-2 text-sm">
								<div class="flex">
									<dt class="w-24 text-gray-500">분류</dt>
									<dd>
										{#if selectedPage.is_event}
											<span class="px-2 py-1 text-xs rounded-full bg-purple-100 text-purple-700">이벤트</span>
										{:else}
											<span class="px-2 py-1 text-xs rounded-full bg-yellow-100 text-yellow-700">미분류</span>
										{/if}
									</dd>
								</div>
								{#if selectedPage.analysis_result}
									{@const result = selectedPage.analysis_result as Record<string, string>}
									{#if result.reason}
										<div class="flex">
											<dt class="w-24 text-gray-500">판단 근거</dt>
											<dd class="text-gray-700">{result.reason}</dd>
										</div>
									{/if}
									{#if result.event_type}
										<div class="flex">
											<dt class="w-24 text-gray-500">이벤트 유형</dt>
											<dd class="text-gray-700">{result.event_type}</dd>
										</div>
									{/if}
									{#if result.summary}
										<div>
											<dt class="text-gray-500 mb-1">요약</dt>
											<dd class="bg-white rounded p-2 text-xs text-gray-600">{result.summary}</dd>
										</div>
									{/if}
								{/if}
							</dl>
						</div>
					{/if}
				{/if}
			</div>

			<div class="mt-6 flex gap-2 justify-end">
				{#if selectedRequest && canAnalyze(selectedRequest) && $isAdmin}
					<button
						onclick={() => selectedRequest && handleAnalyze(selectedRequest)}
						disabled={Boolean(selectedRequest.crawled_page_id && analyzingPages.has(selectedRequest.crawled_page_id))}
						class="btn btn-outline btn-sm text-purple-600 border-purple-300 hover:bg-purple-50 disabled:opacity-50"
					>
						{#if selectedRequest.crawled_page_id && analyzingPages.has(selectedRequest.crawled_page_id)}
							<span class="flex items-center gap-2">
								<span class="animate-spin h-4 w-4 border-2 border-purple-600 border-t-transparent rounded-full"></span>
								분석 중...
							</span>
						{:else}
							AI 분석
						{/if}
					</button>
				{/if}
				{#if (selectedRequest.status === 'failed' || selectedRequest.status === 'completed') && $isAdmin}
					<button onclick={() => selectedRequest && handleRetry(selectedRequest.id)} class="btn btn-outline btn-sm">
						재시도
					</button>
				{/if}
				<button onclick={() => (showDetailModal = false)} class="btn btn-secondary btn-sm">닫기</button>
			</div>
		</div>
	</div>
{/if}
