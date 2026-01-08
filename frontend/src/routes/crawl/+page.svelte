<script lang="ts">
	import { Button } from '$lib/components/ui';

	/**
	 * 크롤링 요청 이력 페이지
	 */
	import { onMount } from 'svelte';
	import { crawlApi, type UniversalCrawlRequest, type CrawledPage } from '$lib/api';
	import { toast } from '$lib/stores/toast';
	import { isAdmin } from '$lib/stores/auth';

	// 상태
	let requests: UniversalCrawlRequest[] = $state([]);
	let total = $state(0);
	let currentPage = $state(1);
	let pageSize = 20;
	let loading = $state(true);
	let error: string | null = $state(null);

	// 필터
	let filterStatus: string | null = $state(null);
	let filterUrlType: string | null = $state(null);

	// 크롤링 요청 모달
	let showAddModal = $state(false);
	let newUrl = $state('');
	let submitting = $state(false);

	// 상세 보기 모달
	let showDetailModal = $state(false);
	let selectedRequest: UniversalCrawlRequest | null = $state(null);
	let selectedPage: CrawledPage | null = $state(null);
	let loadingDetail = $state(false);

	async function fetchRequests() {
		loading = true;
		try {
			const params: Record<string, unknown> = {
				page: currentPage,
				page_size: pageSize
			};
			if (filterStatus) params.status = filterStatus;
			if (filterUrlType) params.url_type = filterUrlType;

			const response = await crawlApi.listRequests(params);
			requests = response.items;
			total = response.total;
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
			const response = await crawlApi.createUrlRequest({
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
			await crawlApi.retryUniversalRequest(requestId);
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
			case 'pending':
				return 'bg-warning-light text-warning-foreground';
			case 'processing':
				return 'bg-primary-light text-primary';
			case 'completed':
				return 'bg-success-light text-success';
			case 'failed':
				return 'bg-error-light text-error';
			default:
				return 'bg-muted text-foreground';
		}
	}

	function getStatusText(status: string) {
		switch (status) {
			case 'pending':
				return '대기';
			case 'processing':
				return '처리 중';
			case 'completed':
				return '완료';
			case 'failed':
				return '실패';
			default:
				return status;
		}
	}

	function getUrlTypeBadge(urlType: string) {
		switch (urlType) {
			case 'google_form':
				return 'bg-primary-light text-primary';
			case 'naver_form':
				return 'bg-success-light text-success';
			case 'naver_blog':
				return 'bg-emerald-100 text-emerald-700';
			default:
				return 'bg-muted text-muted-foreground';
		}
	}

	function getAnalysisResult(req: UniversalCrawlRequest) {
		if (!req.crawled_page) return { text: '-', badge: 'text-muted-foreground' };
		if (req.crawled_page.is_event === null || req.crawled_page.is_event === undefined) {
			return { text: '미분석', badge: 'bg-muted text-muted-foreground' };
		}
		if (req.crawled_page.is_event) {
			return { text: '이벤트', badge: 'bg-purple-light text-purple' };
		}
		return { text: '미분류', badge: 'bg-warning-light text-warning-foreground' };
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

	onMount(() => {
		fetchRequests();
		// 30초마다 자동 갱신
		const interval = setInterval(fetchRequests, 30000);
		return () => clearInterval(interval);
	});
</script>

<svelte:head>
	<title>크롤링 이력</title>
</svelte:head>

<div class="p-4 md:p-6">
	<!-- 헤더 -->
	<div class="mb-4 md:mb-6 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
		<div class="flex items-center gap-3">
			<h2 class="text-xl md:text-2xl font-bold text-foreground">크롤링 이력</h2>
			<span class="text-sm text-muted-foreground">총 {total}건</span>
		</div>

		{#if $isAdmin}
			<Button variant="primary"sm on:click={() => (showAddModal = true)}>
				+ URL 크롤링 요청
			</Button>
		{/if}
	</div>

	<!-- 필터 -->
	<div class="mb-4 flex flex-wrap gap-2">
		<button
			onclick={() => handleStatusFilter(null)}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === null
				? 'bg-gray-800 text-white'
				: 'bg-muted text-muted-foreground hover:bg-secondary'}"
		>
			전체
		</Button>
		<button
			onclick={() => handleStatusFilter('pending')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'pending'
				? 'bg-yellow-600 text-white'
				: 'bg-warning-light text-warning-foreground hover:bg-yellow-200'}"
		>
			대기
		</Button>
		<button
			onclick={() => handleStatusFilter('processing')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'processing'
				? 'bg-primary text-white'
				: 'bg-primary-light text-primary hover:bg-blue-200'}"
		>
			처리 중
		</Button>
		<button
			onclick={() => handleStatusFilter('completed')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'completed'
				? 'bg-success text-white'
				: 'bg-success-light text-success hover:bg-green-200'}"
		>
			완료
		</Button>
		<button
			onclick={() => handleStatusFilter('failed')}
			class="px-3 py-1.5 text-sm rounded-full transition-colors {filterStatus === 'failed'
				? 'bg-error text-white'
				: 'bg-error-light text-error hover:bg-red-200'}"
		>
			실패
		</Button>
	</div>

	<!-- 목록 -->
	{#if loading && requests.length === 0}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if requests.length === 0}
		<div class="text-center py-12 text-muted-foreground">
			<p class="text-lg">크롤링 요청 이력이 없습니다</p>
			{#if $isAdmin}
				<button onclick={() => (showAddModal = true)} class="mt-4 btn btn-primary btn-sm">
					+ URL 크롤링 요청
				</Button>
			{/if}
		</div>
	{:else}
		<!-- 모바일 카드 뷰 -->
		<div class="md:hidden space-y-3">
			{#each requests as req}
				<button
					onclick={() => openDetail(req)}
					class="w-full text-left bg-card border rounded-lg p-4 hover:shadow-md transition-shadow"
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
					<p class="text-sm text-foreground break-all line-clamp-2 mb-2">{req.url}</p>
					<div class="flex justify-between text-xs text-muted-foreground">
						<span>{formatDate(req.requested_at)}</span>
						{#if (req.status === 'failed' || req.status === 'completed') && $isAdmin}
							<button
								onclick={(e) => {
									e.stopPropagation();
									handleRetry(req.id);
								}}
								class="text-primary hover:underline"
							>
								재시도
							</Button>
						{/if}
					</div>
				</Button>
			{/each}
		</div>

		<!-- 데스크톱 테이블 뷰 -->
		<div class="hidden md:block overflow-x-auto">
			<table class="w-full">
				<thead>
					<tr class="border-b text-left text-sm text-muted-foreground">
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
						<tr class="border-b hover:bg-muted cursor-pointer" onclick={() => openDetail(req)}>
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
								<span class="text-sm text-foreground break-all line-clamp-1">{req.url}</span>
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
							<td class="py-3 text-sm text-muted-foreground">{formatDate(req.requested_at)}</td>
							<td class="py-3 text-sm text-muted-foreground">
								{req.completed_at ? formatDate(req.completed_at) : '-'}
							</td>
							<td class="py-3">
								{#if (req.status === 'failed' || req.status === 'completed') && $isAdmin}
									<button
										onclick={(e) => {
											e.stopPropagation();
											handleRetry(req.id);
										}}
										class="text-sm text-primary hover:underline"
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
		{#if total > pageSize}
			<div class="flex justify-between items-center mt-6">
				<span class="text-sm text-muted-foreground">
					{(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)} / {total}
				</span>
				<div class="flex gap-2">
					<button
						onclick={() => {
							currentPage--;
							fetchRequests();
						}}
						disabled={currentPage === 1}
						class="btn btn-secondary btn-sm disabled:opacity-50"
					>
						이전
					</Button>
					<button
						onclick={() => {
							currentPage++;
							fetchRequests();
						}}
						disabled={currentPage * pageSize >= total}
						class="btn btn-secondary btn-sm disabled:opacity-50"
					>
						다음
					</Button>
				</div>
			</div>
		{/if}
	{/if}
</div>

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
				<button onclick={() => (showAddModal = false)} class="text-muted-foreground hover:text-muted-foreground text-2xl">
					&times;
				</Button>
			</div>

			<div class="space-y-4">
				<div>
					<label for="crawl-url" class="block text-sm font-medium text-foreground mb-1">URL</label>
					<input
						id="crawl-url"
						type="url"
						bind:value={newUrl}
						placeholder="https://forms.gle/... 또는 https://blog.naver.com/..."
						class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
						onkeydown={(e) => e.key === 'Enter' && handleAddRequest()}
					/>
					<p class="mt-1 text-xs text-muted-foreground">
						구글폼, 네이버폼, 네이버 블로그 등 지원
					</p>
				</div>
			</div>

			<div class="mt-6 flex gap-2 justify-end">
				<Button variant="secondary"sm on:click={() => (showAddModal = false)}>취소</Button>
				<button onclick={handleAddRequest} disabled={submitting} class="btn btn-primary btn-sm disabled:opacity-50">
					{#if submitting}
						<span class="flex items-center gap-2">
							<span class="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
							요청 중...
						</span>
					{:else}
						요청
					{/if}
				</Button>
			</div>
		</div>
	</div>
{/if}

<!-- 상세 모달 -->
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
				<button onclick={() => (showDetailModal = false)} class="text-muted-foreground hover:text-muted-foreground text-2xl">
					&times;
				</Button>
			</div>

			<div class="space-y-4">
				<!-- 요청 정보 -->
				<div class="bg-background rounded-lg p-4">
					<h4 class="text-sm font-medium text-foreground mb-2">요청 정보</h4>
					<dl class="space-y-2 text-sm">
						<div class="flex">
							<dt class="w-24 text-muted-foreground">URL</dt>
							<dd class="flex-1 break-all">
								<a href={selectedRequest.url} target="_blank" class="text-primary hover:underline">
									{selectedRequest.url}
								</a>
							</dd>
						</div>
						<div class="flex">
							<dt class="w-24 text-muted-foreground">타입</dt>
							<dd>{selectedRequest.url_type}</dd>
						</div>
						<div class="flex">
							<dt class="w-24 text-muted-foreground">요청 시간</dt>
							<dd>{new Date(selectedRequest.requested_at).toLocaleString('ko-KR')}</dd>
						</div>
						{#if selectedRequest.completed_at}
							<div class="flex">
								<dt class="w-24 text-muted-foreground">완료 시간</dt>
								<dd>{new Date(selectedRequest.completed_at).toLocaleString('ko-KR')}</dd>
							</div>
						{/if}
						{#if selectedRequest.error_message}
							<div class="flex">
								<dt class="w-24 text-muted-foreground">오류</dt>
								<dd class="text-error">{selectedRequest.error_message}</dd>
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
					<div class="bg-primary-light rounded-lg p-4">
						<h4 class="text-sm font-medium text-foreground mb-2">크롤링 결과</h4>
						<dl class="space-y-2 text-sm">
							{#if selectedPage.title}
								<div class="flex">
									<dt class="w-24 text-muted-foreground">제목</dt>
									<dd class="font-medium">{selectedPage.title}</dd>
								</div>
							{/if}
							{#if selectedPage.description}
								<div class="flex">
									<dt class="w-24 text-muted-foreground">설명</dt>
									<dd class="text-foreground">{selectedPage.description}</dd>
								</div>
							{/if}
							{#if selectedPage.extractor_used}
								<div class="flex">
									<dt class="w-24 text-muted-foreground">추출기</dt>
									<dd>{selectedPage.extractor_used}</dd>
								</div>
							{/if}
							{#if selectedPage.content}
								<div>
									<dt class="text-muted-foreground mb-1">본문 (일부)</dt>
									<dd class="bg-white rounded p-2 text-xs text-muted-foreground max-h-32 overflow-auto whitespace-pre-wrap">
										{selectedPage.content.substring(0, 500)}{selectedPage.content.length > 500 ? '...' : ''}
									</dd>
								</div>
							{/if}
						</dl>
					</div>
				{/if}
			</div>

			<div class="mt-6 flex gap-2 justify-end">
				{#if (selectedRequest.status === 'failed' || selectedRequest.status === 'completed') && $isAdmin}
					<button onclick={() => handleRetry(selectedRequest.id)} class="btn btn-outline btn-sm">
						재시도
					</Button>
				{/if}
				<Button variant="secondary"sm on:click={() => (showDetailModal = false)}>닫기</Button>
			</div>
		</div>
	</div>
{/if}
