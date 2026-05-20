<script lang="ts">
	import { onMount } from 'svelte';
	import { ThumbsUp, ThumbsDown, Check, X, Circle } from 'lucide-svelte';
	import { writingApi, keywordApi, type GeneratedWriting, type WritingStats, type WritingSource, type KeywordStats, type KeywordStatsResponse, type Stopword, type WritingElement, type WritingElementStats, type WritingBatch, type WritingBatchStatus } from '$lib/api';
	import { Button } from '$lib/components/ui';
	import { createOffsetPagination, createPagePagination } from '$lib/utils/pagination.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import { toast } from '$lib/stores/toast';
	import { confirm } from '$lib/stores/confirm';

	// 상태
	let writings: GeneratedWriting[] = [];
	let sources: WritingSource[] = [];
	let stats: WritingStats | null = null;
	let loading = true;
	let error: string | null = null;

	// 배치 상태
	let batches: WritingBatch[] = [];
	const batchPager = createPagePagination(10);
	let activeBatch: WritingBatchStatus | null = null;
	let batchPolling: ReturnType<typeof setInterval> | null = null;
	let creatingBatch = false;

	// 키워드 상태
	let keywords: KeywordStats[] = [];
	let keywordStats: KeywordStatsResponse | null = null;
	let stopwords: Stopword[] = [];
	const keywordPager = createOffsetPagination(100);
	let keywordMinFreq = 10;
	let analyzing = false;
	let analyzeResult: { mode: string; saved_keywords?: number; new_keywords?: number; updated_keywords?: number } | null = null;

	// 소재 상태
	let elements: WritingElement[] = [];
	let elementStats: WritingElementStats | null = null;
	const elementPager = createPagePagination(50);
	let elementFilterCategory = '';
	let elementFilterSourceType = '';
	let extracting = false;
	let extractResult: { success: boolean; created_requests: number } | null = null;

	// 탭
	type Tab = 'writings' | 'sources' | 'keywords' | 'elements' | 'batches';
	let activeTab: Tab = 'writings';

	$: writingSubTabs = [
		{ id: 'writings', label: '생성된 글', count: stats?.generated_count ?? 0 },
		{ id: 'sources', label: '소스', count: stats?.source_count ?? 0 },
		{ id: 'keywords', label: '키워드', count: keywordStats?.total_keywords ?? 0 },
		{ id: 'elements', label: '소재', count: elementStats?.total ?? 0 },
		{ id: 'batches', label: '배치', count: batchPager.total },
	];

	// 필터
	let filterTaskType = '';
	let filterRating = '';

	// 페이지네이션
	const writingPager = createPagePagination(20);

	// 소스 페이지네이션
	const sourcePager = createPagePagination(50);

	// 모달
	let selectedWriting: GeneratedWriting | null = null;
	let showModal = false;
	let editMode = false;
	let editContent = '';

	// 소스 모달
	let selectedSource: WritingSource | null = null;
	let showSourceModal = false;

	// 수동 실행
	let running = false;
	let runResult: { success: boolean; mix_count: number; random_count: number } | null = null;

	function errorMessage(e: unknown): string {
		return e instanceof Error ? e.message : '알 수 없는 오류';
	}

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const [listRes, statsRes] = await Promise.all([
				writingApi.listGenerated({
					task_type: filterTaskType || undefined,
					rating: filterRating || undefined,
					page: writingPager.page,
					page_size: writingPager.pageSize
				}),
				writingApi.getStats()
			]);

			writings = listRes.items;
			writingPager.total = listRes.total;
			stats = statsRes;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function fetchSources() {
		loading = true;
		error = null;
		try {
			const res = await writingApi.listSources({
				page: sourcePager.page,
				page_size: sourcePager.pageSize
			});
			sources = res.items;
			sourcePager.total = res.total;
		} catch (e) {
			error = e instanceof Error ? e.message : '소스 로드 실패';
		} finally {
			loading = false;
		}
	}

	function switchTab(tab: Tab) {
		activeTab = tab;
		// 배치 탭에서 벗어나면 폴링 중지
		if (tab !== 'batches' && batchPolling) {
			clearInterval(batchPolling);
			batchPolling = null;
		}
		if (tab === 'writings') {
			fetchData();
		} else if (tab === 'sources') {
			fetchSources();
		} else if (tab === 'keywords') {
			fetchKeywords();
		} else if (tab === 'elements') {
			fetchElements();
		} else if (tab === 'batches') {
			fetchBatches();
		}
	}

	async function fetchElements() {
		loading = true;
		error = null;
		try {
			const [listRes, statsRes] = await Promise.all([
				writingApi.listElements({
					category: elementFilterCategory || undefined,
					source_type: elementFilterSourceType || undefined,
					page: elementPager.page,
					page_size: elementPager.pageSize
				}),
				writingApi.getElementsStats()
			]);
			elements = listRes.items;
			elementPager.total = listRes.total;
			elementStats = statsRes;
		} catch (e) {
			error = e instanceof Error ? e.message : '소재 로드 실패';
		} finally {
			loading = false;
		}
	}

	function handleElementFilter() {
		elementPager.reset();
		fetchElements();
	}

	function elementPrevPage() {
		elementPager.prev();
		fetchElements();
	}

	function elementNextPage() {
		elementPager.next();
		fetchElements();
	}

	async function deleteElement(id: number, name: string) {
		if (!await confirm({ title: '소재 삭제', message: `"${name}" 소재를 삭제하시겠습니까?`, confirmText: '삭제', variant: 'danger' })) return;
		try {
			await writingApi.deleteElement(id);
			await fetchElements();
		} catch (e) {
			toast.error('삭제 실패: ' + errorMessage(e));
		}
	}

	async function extractTopics() {
		if (extracting) return;
		const limitStr = prompt('추출할 소스 수 (기본: 100, 최대: 500)', '100');
		if (!limitStr) return;
		const limit = parseInt(limitStr);
		if (isNaN(limit) || limit < 1 || limit > 500) {
			toast.warning('1~500 사이의 숫자를 입력하세요.');
			return;
		}

		extracting = true;
		extractResult = null;
		try {
			const result = await writingApi.extractTopics(limit);
			extractResult = result;
			toast.success(`${result.created_requests}개의 추출 요청이 생성되었습니다. Claude Worker가 처리합니다.`);
		} catch (e) {
			toast.error('추출 요청 실패: ' + errorMessage(e));
		} finally {
			extracting = false;
		}
	}

	function getSourceTypeLabel(type: string): string {
		if (type === 'auto') return '자동 추출';
		if (type === 'manual') return '수동 추가';
		return '시드';
	}

	function getSourceTypeClass(type: string): string {
		if (type === 'auto') return 'bg-success-light text-success';
		if (type === 'manual') return 'bg-primary-light text-primary';
		return 'bg-muted text-muted-foreground';
	}

	async function fetchKeywords() {
		loading = true;
		error = null;
		try {
			const [listRes, statsRes] = await Promise.all([
				keywordApi.list({
					limit: keywordPager.limit,
					offset: keywordPager.offset,
					min_frequency: keywordMinFreq,
					include_stopwords: false,
					include_promoted: true
				}),
				keywordApi.stats()
			]);
			keywords = listRes.items;
			keywordPager.total = listRes.total;
			keywordStats = statsRes;
		} catch (e) {
			error = e instanceof Error ? e.message : '키워드 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function runAnalysis(mode: 'full' | 'incremental') {
		if (analyzing) return;
		const confirmMsg = mode === 'full'
			? '전체 분석을 실행하시겠습니까? (기존 데이터가 초기화됩니다)'
			: '증분 분석을 실행하시겠습니까?';
		if (!await confirm({ title: '키워드 분석', message: confirmMsg, confirmText: '실행', variant: mode === 'full' ? 'danger' : 'default' })) return;

		analyzing = true;
		analyzeResult = null;
		try {
			const result = await keywordApi.analyze({ mode });
			analyzeResult = result;
			await fetchKeywords();
		} catch (e) {
			toast.error('분석 실패: ' + errorMessage(e));
		} finally {
			analyzing = false;
		}
	}

	async function promoteKeyword(kw: KeywordStats) {
		if (!await confirm({ title: '키워드 승격', message: `"${kw.keyword}"를 writing_elements로 승격하시겠습니까?`, confirmText: '승격' })) return;
		try {
			await keywordApi.promote(kw.id);
			toast.success(`"${kw.keyword}" 승격 완료`);
			await fetchKeywords();
		} catch (e) {
			toast.error('승격 실패: ' + errorMessage(e));
		}
	}

	async function demoteKeyword(kw: KeywordStats) {
		if (!await confirm({ title: '승격 취소', message: `"${kw.keyword}" 승격을 취소하시겠습니까?`, confirmText: '취소' })) return;
		try {
			await keywordApi.demote(kw.id);
			toast.success(`"${kw.keyword}" 승격 취소 완료`);
			await fetchKeywords();
		} catch (e) {
			toast.error('승격 취소 실패: ' + errorMessage(e));
		}
	}

	async function markAsStopword(kw: KeywordStats) {
		if (!await confirm({ title: '불용어 처리', message: `"${kw.keyword}"를 불용어로 마킹하시겠습니까?`, confirmText: '처리' })) return;
		try {
			await keywordApi.markStopword(kw.id);
			toast.success(`"${kw.keyword}" 불용어 처리 완료`);
			await fetchKeywords();
		} catch (e) {
			toast.error('불용어 마킹 실패: ' + errorMessage(e));
		}
	}

	async function promoteBatch() {
		const limit = prompt('승격할 키워드 수 (기본: 50)', '50');
		if (!limit) return;
		const minFreq = prompt('최소 빈도수 (기본: 100)', '100');
		if (!minFreq) return;

		try {
			const result = await keywordApi.promoteBatch({
				limit: parseInt(limit),
				min_frequency: parseInt(minFreq)
			});
			toast.success(`${result.promoted_count}개 키워드가 승격되었습니다.`);
			await fetchKeywords();
		} catch (e) {
			toast.error('일괄 승격 실패: ' + errorMessage(e));
		}
	}

	function keywordPrevPage() {
		if (keywordPager.offset > 0) {
			keywordPager.offset = Math.max(0, keywordPager.offset - keywordPager.limit);
			fetchKeywords();
		}
	}

	function keywordNextPage() {
		if (keywordPager.hasMore) {
			keywordPager.offset += keywordPager.limit;
			fetchKeywords();
		}
	}

	function handleKeywordFilter() {
		keywordPager.reset();
		fetchKeywords();
	}

	function handleFilter() {
		writingPager.reset();
		fetchData();
	}

	function clearFilters() {
		filterTaskType = '';
		filterRating = '';
		handleFilter();
	}

	function prevPage() {
		writingPager.prev();
		fetchData();
	}

	function nextPage() {
		writingPager.next();
		fetchData();
	}

	function sourcePrevPage() {
		sourcePager.prev();
		fetchSources();
	}

	function sourceNextPage() {
		sourcePager.next();
		fetchSources();
	}

	async function openWritingModal(writing: GeneratedWriting) {
		try {
			const full = await writingApi.getGenerated(writing.id);
			selectedWriting = full;
			editContent = full.content;
			editMode = false;
			showModal = true;
		} catch (e) {
			toast.error('상세 조회 실패: ' + errorMessage(e));
		}
	}

	function closeModal() {
		showModal = false;
		selectedWriting = null;
		editMode = false;
	}

	async function openSourceModal(source: WritingSource) {
		try {
			const full = await writingApi.getSource(source.id);
			selectedSource = full;
			showSourceModal = true;
		} catch (e) {
			toast.error('소스 조회 실패: ' + errorMessage(e));
		}
	}

	function closeSourceModal() {
		showSourceModal = false;
		selectedSource = null;
	}

	async function saveEdit() {
		if (!selectedWriting) return;
		try {
			await writingApi.updateGenerated(selectedWriting.id, { content: editContent });
			toast.success('저장되었습니다.');
			editMode = false;
			await fetchData();
			// 모달 내용 업데이트
			const updated = await writingApi.getGenerated(selectedWriting.id);
			selectedWriting = updated;
		} catch (e) {
			toast.error('저장 실패: ' + errorMessage(e));
		}
	}

	async function rateWriting(rating: number | null) {
		if (!selectedWriting) return;
		try {
			await writingApi.rateGenerated(selectedWriting.id, rating);
			selectedWriting.rating = rating;
			await fetchData();
		} catch (e) {
			toast.error('평가 실패: ' + errorMessage(e));
		}
	}

	async function deleteWriting() {
		if (!selectedWriting) return;
		if (!await confirm({ title: '글 삭제', message: '이 글을 삭제하시겠습니까?', confirmText: '삭제', variant: 'danger' })) return;
		try {
			await writingApi.deleteGenerated(selectedWriting.id);
			closeModal();
			await fetchData();
		} catch (e) {
			toast.error('삭제 실패: ' + errorMessage(e));
		}
	}

	async function deleteSource() {
		if (!selectedSource) return;
		if (!await confirm({ title: '소스 삭제', message: '이 소스를 삭제하시겠습니까?', confirmText: '삭제', variant: 'danger' })) return;
		try {
			await writingApi.deleteSource(selectedSource.id);
			closeSourceModal();
			await fetchSources();
		} catch (e) {
			toast.error('삭제 실패: ' + errorMessage(e));
		}
	}

	async function runWritingTask() {
		if (running) return;
		if (!await confirm({ title: '작문 태스크 실행', message: '작문 태스크를 수동 실행하시겠습니까? (mix 5개 + random 3개)', confirmText: '실행' })) return;

		running = true;
		runResult = null;
		try {
			const result = await writingApi.run();
			runResult = result;
			await fetchData();
		} catch (e) {
			toast.error('실행 실패: ' + errorMessage(e));
		} finally {
			running = false;
		}
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

	function getTaskTypeLabel(type: string): string {
		return type === 'mix' ? '소스 혼합' : type === 'random' ? '랜덤 작문' : type === 'keyword' ? '키워드' : type;
	}

	// ============================================================
	// 배치 관련 함수
	// ============================================================

	async function fetchBatches() {
		loading = true;
		error = null;
		try {
			const res = await writingApi.listBatches({
				page: batchPager.page,
				page_size: batchPager.pageSize
			});
			batches = res.items;
			batchPager.total = res.total;
		} catch (e) {
			error = e instanceof Error ? e.message : '배치 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function createBatch() {
		if (creatingBatch) return;
		if (!await confirm({ title: '배치 생성', message: '새 글쓰기 배치를 생성하시겠습니까? (11개 LLM 요청)', confirmText: '생성' })) return;

		creatingBatch = true;
		try {
			const result = await writingApi.createBatch();
			toast.success(result.message);
			await fetchBatches();
			// 생성 후 바로 해당 배치 상태 확인
			await viewBatchStatus(result.batch_id);
		} catch (e) {
			toast.error('배치 생성 실패: ' + errorMessage(e));
		} finally {
			creatingBatch = false;
		}
	}

	async function viewBatchStatus(batchId: number) {
		try {
			activeBatch = await writingApi.getBatchStatus(batchId);
			// 진행 중이면 폴링 시작
			if (activeBatch && activeBatch.status === 'running') {
				startBatchPolling(batchId);
			}
		} catch (e) {
			toast.error('배치 상태 조회 실패: ' + errorMessage(e));
		}
	}

	function startBatchPolling(batchId: number) {
		if (batchPolling) {
			clearInterval(batchPolling);
		}
		batchPolling = setInterval(async () => {
			try {
				activeBatch = await writingApi.getBatchStatus(batchId);
				// 완료되면 폴링 중지
				if (activeBatch && (activeBatch.status === 'completed' || activeBatch.status === 'failed')) {
					if (batchPolling) {
						clearInterval(batchPolling);
						batchPolling = null;
					}
					await fetchBatches(); // 목록 새로고침
				}
			} catch (e) {
				console.error('배치 폴링 실패:', e);
			}
		}, 3000); // 3초마다 폴링
	}

	function closeBatchModal() {
		activeBatch = null;
		if (batchPolling) {
			clearInterval(batchPolling);
			batchPolling = null;
		}
	}

	function getBatchStatusLabel(status: string): string {
		switch (status) {
			case 'pending': return '대기';
			case 'running': return '진행 중';
			case 'completed': return '완료';
			case 'failed': return '실패';
			default: return status;
		}
	}

	function getBatchStatusClass(status: string): string {
		switch (status) {
			case 'pending': return 'bg-muted text-foreground';
			case 'running': return 'bg-primary-light text-primary';
			case 'completed': return 'bg-success-light text-success';
			case 'failed': return 'bg-error-light text-error';
			default: return 'bg-muted text-muted-foreground';
		}
	}

	function batchPrevPage() {
		batchPager.prev();
		fetchBatches();
	}

	function batchNextPage() {
		batchPager.next();
		fetchBatches();
	}

	function getRatingComponent(rating: number | null) {
		if (rating === 1) return ThumbsUp;
		if (rating === -1) return ThumbsDown;
		return null;
	}

	onMount(() => {
		fetchData();
	});
</script>

<div>
	<!-- 헤더 -->
	<div class="mb-6 flex justify-between items-center">
		<h2 class="text-lg font-bold text-foreground">글쓰기 워커</h2>
		<div class="flex gap-2">
			<Button
				onclick={runWritingTask}
				disabled={running}
				variant="primary"
				size="sm"
			>
				{running ? '실행 중...' : '수동 실행'}
			</Button>
			<Button onclick={() => switchTab(activeTab)} variant="secondary" size="sm">
				새로고침
			</Button>
		</div>
	</div>

	<!-- 실행 결과 알림 -->
	{#if runResult}
		<div class="mb-4 p-4 bg-success-light border border-green-200 text-success rounded-lg">
			실행 완료: 소스 혼합 {runResult.mix_count}개, 랜덤 작문 {runResult.random_count}개 생성됨
			<button onclick={() => runResult = null} class="ml-4 text-success hover:underline">닫기</button>
		</div>
	{/if}

	<!-- 통계 카드 -->
	{#if stats}
		<div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">소스</div>
				<div class="text-2xl font-bold text-foreground">{stats.source_count}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">생성된 글</div>
				<div class="text-2xl font-bold text-primary">{stats.generated_count}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">소스 혼합</div>
				<div class="text-2xl font-bold text-purple">{stats.by_type.mix}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">랜덤 작문</div>
				<div class="text-2xl font-bold text-primary">{stats.by_type.random}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">오늘 생성</div>
				<div class="text-2xl font-bold text-success">{stats.today_count}</div>
			</div>
		</div>
	{/if}

	<!-- 탭 -->
	<TabNav tabs={writingSubTabs} bind:activeTab variant="secondary" />

	{#if activeTab === 'writings'}
		<!-- 필터 -->
		<div class="mb-4 flex flex-wrap gap-2 items-center">
			<select bind:value={filterTaskType} class="px-3 py-1.5 border border-border rounded-lg text-sm">
				<option value="">전체 타입</option>
				<option value="mix">소스 혼합</option>
				<option value="random">랜덤 작문</option>
			</select>
			<select bind:value={filterRating} class="px-3 py-1.5 border border-border rounded-lg text-sm">
				<option value="">전체 평가</option>
				<option value="1">추천</option>
				<option value="-1">비추천</option>
				<option value="null">미평가</option>
			</select>
			<Button onclick={handleFilter} variant="primary" size="sm">필터</Button>
			<Button onclick={clearFilters} variant="secondary" size="sm">초기화</Button>
		</div>

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
		{:else if writings.length === 0}
			<div class="text-center py-12 text-muted-foreground">
				<p class="text-lg">생성된 글이 없습니다</p>
				<p class="text-sm mt-2">수동 실행 버튼을 눌러 글을 생성해보세요.</p>
			</div>
		{:else}
			<!-- 글 목록 -->
			<div class="md:hidden space-y-3 mb-6">
				{#each writings as writing (writing.id)}
					<article
						class="rounded-lg border border-border bg-card p-3 shadow-sm"
						onclick={() => openWritingModal(writing)}
					>
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<div class="mb-2 flex flex-wrap items-center gap-2">
									<span class="rounded-full px-2 py-1 text-xs {writing.task_type === 'mix' ? 'bg-purple-light text-purple-800' : 'bg-primary-light text-indigo-800'}">
										{getTaskTypeLabel(writing.task_type)}
									</span>
									<span class="text-xs text-muted-foreground">#{writing.id}</span>
								</div>
								<p class="line-clamp-2 text-sm text-foreground">{writing.preview}</p>
							</div>
							<div class="shrink-0 text-right text-xs text-muted-foreground">
								<div>{formatDateTime(writing.created_at)}</div>
								<div class="mt-2 flex justify-end">
									{#if getRatingComponent(writing.rating)}
										<svelte:component
											this={getRatingComponent(writing.rating)}
											size={18}
											class={writing.rating === 1 ? 'text-success' : 'text-error'}
										/>
									{:else}
										<span>-</span>
									{/if}
								</div>
							</div>
						</div>
					</article>
				{/each}
			</div>
			<div class="hidden bg-white rounded-lg border border-border overflow-x-auto mb-6 md:block">
				<table class="w-full min-w-[600px]">
					<thead class="bg-background border-b border-border">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">타입</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">미리보기</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">평가</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">생성일</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each writings as writing (writing.id)}
							<tr
								class="hover:bg-muted cursor-pointer"
								onclick={() => openWritingModal(writing)}
							>
								<td class="px-4 py-3 text-sm text-foreground">{writing.id}</td>
								<td class="px-4 py-3">
									<span class="px-2 py-1 text-xs rounded-full {writing.task_type === 'mix' ? 'bg-purple-light text-purple-800' : 'bg-primary-light text-indigo-800'}">
										{getTaskTypeLabel(writing.task_type)}
									</span>
								</td>
								<td class="px-4 py-3 text-sm text-foreground max-w-md truncate">{writing.preview}</td>
								<td class="px-4 py-3">
									{#if getRatingComponent(writing.rating)}
										<svelte:component
											this={getRatingComponent(writing.rating)}
											size={18}
											class={writing.rating === 1 ? 'text-success' : 'text-error'}
										/>
									{:else}
										<span class="text-muted-foreground">-</span>
									{/if}
								</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(writing.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			{#if writingPager.totalPages > 1}
				<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
					<span class="text-sm text-muted-foreground">
						전체 {writingPager.total}개 중 {(writingPager.page - 1) * writingPager.pageSize + 1} - {Math.min(writingPager.page * writingPager.pageSize, writingPager.total)}
					</span>
					<div class="flex gap-2">
						<Button onclick={prevPage} disabled={writingPager.page === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{writingPager.page} / {writingPager.totalPages}</span>
						<Button onclick={nextPage} disabled={writingPager.page >= writingPager.totalPages} variant="secondary" size="sm">
							다음
						</Button>
					</div>
				</div>
			{/if}
		{/if}
	{:else if activeTab === 'sources'}
		<!-- 소스 목록 -->
		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
		{:else if sources.length === 0}
			<div class="text-center py-12 text-muted-foreground">
				<p class="text-lg">소스가 없습니다</p>
				<p class="text-sm mt-2">DB에 소스를 추가해주세요.</p>
			</div>
		{:else}
			<div class="md:hidden space-y-3 mb-6">
				{#each sources as source (source.id)}
					<article
						class="rounded-lg border border-border bg-card p-3 shadow-sm"
						onclick={() => openSourceModal(source)}
					>
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<div class="mb-2 flex flex-wrap items-center gap-2">
									<span class="rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground">#{source.id}</span>
									<span class="rounded-full bg-primary-light px-2 py-1 text-xs text-primary">{source.category || '미분류'}</span>
								</div>
								<p class="line-clamp-2 text-sm text-foreground">{source.preview}</p>
								<p class="mt-1 truncate text-xs text-muted-foreground">{source.source_info || '-'}</p>
							</div>
							<div class="shrink-0 text-right text-xs text-muted-foreground">{formatDateTime(source.created_at)}</div>
						</div>
					</article>
				{/each}
			</div>
			<div class="hidden bg-white rounded-lg border border-border overflow-x-auto mb-6 md:block">
				<table class="w-full min-w-[500px]">
					<thead class="bg-background border-b border-border">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">카테고리</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">미리보기</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">출처</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">생성일</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each sources as source (source.id)}
							<tr
								class="hover:bg-muted cursor-pointer"
								onclick={() => openSourceModal(source)}
							>
								<td class="px-4 py-3 text-sm text-foreground">{source.id}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{source.category || '-'}</td>
								<td class="px-4 py-3 text-sm text-foreground max-w-md truncate">{source.preview}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{source.source_info || '-'}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(source.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 소스 페이지네이션 -->
			{#if sourcePager.totalPages > 1}
				<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
					<span class="text-sm text-muted-foreground">
						전체 {sourcePager.total}개 중 {(sourcePager.page - 1) * sourcePager.pageSize + 1} - {Math.min(sourcePager.page * sourcePager.pageSize, sourcePager.total)}
					</span>
					<div class="flex gap-2">
						<Button onclick={sourcePrevPage} disabled={sourcePager.page === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{sourcePager.page} / {sourcePager.totalPages}</span>
						<Button onclick={sourceNextPage} disabled={sourcePager.page >= sourcePager.totalPages} variant="secondary" size="sm">
							다음
						</Button>
					</div>
				</div>
			{/if}
		{/if}
	{:else if activeTab === 'keywords'}
		<!-- 키워드 통계 -->
		{#if keywordStats}
			<div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">전체 키워드</div>
					<div class="text-2xl font-bold text-foreground">{keywordStats.total_keywords.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">승격됨</div>
					<div class="text-2xl font-bold text-success">{keywordStats.promoted.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">불용어</div>
					<div class="text-2xl font-bold text-error">{keywordStats.stopwords.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">검토됨</div>
					<div class="text-2xl font-bold text-primary">{keywordStats.reviewed.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">미검토</div>
					<div class="text-2xl font-bold text-warning">{keywordStats.pending_review.toLocaleString()}</div>
				</div>
			</div>
		{/if}

		<!-- 분석 결과 알림 -->
		{#if analyzeResult}
			<div class="mb-4 p-4 bg-success-light border border-green-200 text-success rounded-lg">
				분석 완료 ({analyzeResult.mode}):
				{#if analyzeResult.saved_keywords}
					{analyzeResult.saved_keywords.toLocaleString()}개 키워드 저장
				{:else}
					신규 {analyzeResult.new_keywords ?? 0}개, 업데이트 {analyzeResult.updated_keywords ?? 0}개
				{/if}
				<button onclick={() => analyzeResult = null} class="ml-4 text-success hover:underline">닫기</button>
			</div>
		{/if}

		<!-- 키워드 필터 및 액션 -->
		<div class="mb-4 flex flex-wrap gap-2 items-center justify-between">
			<div class="flex gap-2 items-center">
				<label class="text-sm text-muted-foreground">최소 빈도:</label>
				<input
					type="number"
					bind:value={keywordMinFreq}
					min="1"
					class="w-20 px-2 py-1 border border-border rounded text-sm"
				/>
				<Button onclick={handleKeywordFilter} variant="primary" size="sm">필터</Button>
			</div>
			<div class="flex gap-2">
				<Button
					onclick={() => runAnalysis('incremental')}
					disabled={analyzing}
					variant="secondary"
					size="sm"
				>
					{analyzing ? '분석 중...' : '증분 분석'}
				</Button>
				<Button
					onclick={() => runAnalysis('full')}
					disabled={analyzing}
					variant="secondary"
					size="sm"
				>
					전체 분석
				</Button>
				<Button onclick={promoteBatch} variant="primary" size="sm">
					일괄 승격
				</Button>
			</div>
		</div>

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
		{:else if keywords.length === 0}
			<div class="text-center py-12 text-muted-foreground">
				<p class="text-lg">키워드가 없습니다</p>
				<p class="text-sm mt-2">분석 버튼을 눌러 키워드를 추출해보세요.</p>
			</div>
		{:else}
			<!-- 키워드 목록 -->
			<div class="md:hidden space-y-3 mb-6">
				{#each keywords as kw (kw.id)}
					<article class="rounded-lg border border-border bg-card p-3 shadow-sm">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<h3 class="truncate text-sm font-medium text-foreground">{kw.keyword}</h3>
								<div class="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
									<span>빈도 {kw.frequency.toLocaleString()}</span>
									<span>소스 {kw.source_count.toLocaleString()}</span>
								</div>
							</div>
							<div class="shrink-0">
								{#if kw.is_promoted}
									<span class="rounded-full bg-success-light px-2 py-1 text-xs text-success">승격됨</span>
								{:else if kw.is_stopword}
									<span class="rounded-full bg-error-light px-2 py-1 text-xs text-error">불용어</span>
								{:else}
									<span class="rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground">미검토</span>
								{/if}
							</div>
						</div>
						<div class="mt-3 flex flex-wrap justify-end gap-2">
							{#if kw.is_promoted}
								<button onclick={() => demoteKeyword(kw)} class="rounded border border-error/30 px-3 py-1.5 text-xs text-error hover:bg-error-light">삭제</button>
							{:else if !kw.is_stopword}
								<button onclick={() => promoteKeyword(kw)} class="rounded border border-success/30 px-3 py-1.5 text-xs text-success hover:bg-success-light">승격</button>
								<button onclick={() => markAsStopword(kw)} class="rounded border border-error/30 px-3 py-1.5 text-xs text-error hover:bg-error-light">불용어</button>
							{/if}
						</div>
					</article>
				{/each}
			</div>
			<div class="hidden bg-white rounded-lg border border-border overflow-x-auto mb-6 md:block">
				<table class="w-full min-w-[700px]">
					<thead class="bg-background border-b border-border">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">키워드</th>
							<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">빈도</th>
							<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">소스 수</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">상태</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each keywords as kw (kw.id)}
							<tr class="hover:bg-muted">
								<td class="px-4 py-3 text-sm font-medium text-foreground">{kw.keyword}</td>
								<td class="px-4 py-3 text-sm text-right text-foreground">{kw.frequency.toLocaleString()}</td>
								<td class="px-4 py-3 text-sm text-right text-muted-foreground">{kw.source_count.toLocaleString()}</td>
								<td class="px-4 py-3 text-center">
									{#if kw.is_promoted}
										<span class="px-2 py-1 text-xs rounded-full bg-success-light text-success">승격됨</span>
									{:else if kw.is_stopword}
										<span class="px-2 py-1 text-xs rounded-full bg-error-light text-error">불용어</span>
									{:else}
										<span class="px-2 py-1 text-xs rounded-full bg-muted text-muted-foreground">미검토</span>
									{/if}
								</td>
								<td class="px-4 py-3 text-center">
									{#if kw.is_promoted}
										<button
											onclick={() => demoteKeyword(kw)}
											class="text-error hover:text-error text-sm"
										>
											삭제
										</button>
									{:else if !kw.is_stopword}
										<button
											onclick={() => promoteKeyword(kw)}
											class="text-success hover:text-success text-sm mr-2"
										>
											승격
										</button>
										<button
											onclick={() => markAsStopword(kw)}
											class="text-error hover:text-error text-sm"
										>
											불용어
										</button>
									{:else}
										<span class="text-muted-foreground text-sm">-</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			{#if keywordPager.total > keywordPager.limit}
				<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
					<span class="text-sm text-muted-foreground">
						전체 {keywordPager.total.toLocaleString()}개 중 {keywordPager.offset + 1} - {Math.min(keywordPager.offset + keywordPager.limit, keywordPager.total)}
					</span>
					<div class="flex gap-2">
						<Button onclick={keywordPrevPage} disabled={keywordPager.offset === 0} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">
							{Math.floor(keywordPager.offset / keywordPager.limit) + 1} / {Math.ceil(keywordPager.total / keywordPager.limit)}
						</span>
						<Button onclick={keywordNextPage} disabled={!keywordPager.hasMore} variant="secondary" size="sm">
							다음
						</Button>
					</div>
				</div>
			{/if}
		{/if}
	{:else if activeTab === 'elements'}
		<!-- 소재 통계 -->
		{#if elementStats}
			<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">전체 소재</div>
					<div class="text-2xl font-bold text-foreground">{elementStats.total}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">시드</div>
					<div class="text-2xl font-bold text-muted-foreground">{elementStats.topic_by_source?.seed ?? 0}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">자동 추출</div>
					<div class="text-2xl font-bold text-success">{elementStats.topic_by_source?.auto ?? 0}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">수동 추가</div>
					<div class="text-2xl font-bold text-primary">{elementStats.topic_by_source?.manual ?? 0}</div>
				</div>
			</div>
		{/if}

		<!-- 소재 필터 및 액션 -->
		<div class="mb-4 flex flex-wrap gap-2 items-center justify-between">
			<div class="flex gap-2 items-center">
				<select bind:value={elementFilterCategory} class="px-3 py-1.5 border border-border rounded-lg text-sm">
					<option value="">전체 카테고리</option>
					<option value="topic">소재(topic)</option>
					<option value="tone">어조(tone)</option>
					<option value="ending">마무리(ending)</option>
				</select>
				<select bind:value={elementFilterSourceType} class="px-3 py-1.5 border border-border rounded-lg text-sm">
					<option value="">전체 출처</option>
					<option value="seed">시드</option>
					<option value="auto">자동 추출</option>
					<option value="manual">수동 추가</option>
				</select>
				<Button onclick={handleElementFilter} variant="primary" size="sm">필터</Button>
			</div>
			<Button
				onclick={extractTopics}
				disabled={extracting}
				variant="secondary"
				size="sm"
			>
				{extracting ? '추출 중...' : '소재 추출'}
			</Button>
		</div>

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
		{:else if elements.length === 0}
			<div class="text-center py-12 text-muted-foreground">
				<p class="text-lg">소재가 없습니다</p>
				<p class="text-sm mt-2">소재 추출 버튼을 눌러 소재를 수집해보세요.</p>
			</div>
		{:else}
			<!-- 소재 목록 -->
			<div class="md:hidden space-y-3 mb-6">
				{#each elements as elem (elem.id)}
					<article class="rounded-lg border border-border bg-card p-3 shadow-sm">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<h3 class="truncate text-sm font-medium text-foreground">{elem.name}</h3>
								<div class="mt-2 flex flex-wrap gap-2">
									<span class="rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground">{elem.category}</span>
									<span class="rounded-full px-2 py-1 text-xs {getSourceTypeClass(elem.source_type)}">{getSourceTypeLabel(elem.source_type)}</span>
								</div>
							</div>
							<div class="shrink-0 text-right text-xs text-muted-foreground">
								<div>빈도 {elem.frequency}</div>
								<button onclick={() => deleteElement(elem.id, elem.name)} class="mt-2 rounded border border-error/30 px-3 py-1.5 text-xs text-error hover:bg-error-light">
									삭제
								</button>
							</div>
						</div>
					</article>
				{/each}
			</div>
			<div class="hidden bg-white rounded-lg border border-border overflow-x-auto mb-6 md:block">
				<table class="w-full min-w-[600px]">
					<thead class="bg-background border-b border-border">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">소재명</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">카테고리</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">출처</th>
							<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">빈도</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each elements as elem (elem.id)}
							<tr class="hover:bg-muted">
								<td class="px-4 py-3 text-sm font-medium text-foreground">{elem.name}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{elem.category}</td>
								<td class="px-4 py-3 text-center">
									<span class="px-2 py-1 text-xs rounded-full {getSourceTypeClass(elem.source_type)}">
										{getSourceTypeLabel(elem.source_type)}
									</span>
								</td>
								<td class="px-4 py-3 text-sm text-right text-foreground">{elem.frequency}</td>
								<td class="px-4 py-3 text-center">
									<button
										onclick={() => deleteElement(elem.id, elem.name)}
										class="text-error hover:text-error text-sm"
									>
										삭제
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			{#if elementPager.totalPages > 1}
				<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
					<span class="text-sm text-muted-foreground">
						전체 {elementPager.total}개 중 {(elementPager.page - 1) * elementPager.pageSize + 1} - {Math.min(elementPager.page * elementPager.pageSize, elementPager.total)}
					</span>
					<div class="flex gap-2">
						<Button onclick={elementPrevPage} disabled={elementPager.page === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{elementPager.page} / {elementPager.totalPages}</span>
						<Button onclick={elementNextPage} disabled={elementPager.page >= elementPager.totalPages} variant="secondary" size="sm">
							다음
						</Button>
					</div>
				</div>
			{/if}
		{/if}
	{:else if activeTab === 'batches'}
		<!-- 배치 헤더 -->
		<div class="mb-4 flex justify-between items-center">
			<h3 class="text-lg font-semibold text-foreground">글쓰기 배치</h3>
			<Button
				onclick={createBatch}
				disabled={creatingBatch}
				variant="primary"
				size="sm"
			>
				{creatingBatch ? '생성 중...' : '새 배치 생성'}
			</Button>
		</div>

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
		{:else if batches.length === 0}
			<div class="text-center py-12 text-muted-foreground">
				<p class="text-lg">배치가 없습니다</p>
				<p class="text-sm mt-2">'새 배치 생성' 버튼을 눌러 글쓰기를 시작하세요.</p>
			</div>
		{:else}
			<!-- 배치 목록 -->
			<div class="md:hidden space-y-3 mb-6">
				{#each batches as batch (batch.id)}
					<article class="rounded-lg border border-border bg-card p-3 shadow-sm">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<div class="mb-2 flex flex-wrap items-center gap-2">
									<span class="text-sm font-medium text-foreground">배치 #{batch.id}</span>
									<span class="rounded-full px-2 py-1 text-xs {getBatchStatusClass(batch.status)}">{getBatchStatusLabel(batch.status)}</span>
								</div>
								<div class="flex items-center gap-2">
									<div class="h-2 flex-1 rounded-full bg-secondary">
										<div
											class="h-2 rounded-full bg-primary transition-all"
											style="width: {batch.progress_percent}%"
										></div>
									</div>
									<span class="w-16 text-right text-xs text-muted-foreground">{batch.completed}/{batch.total}</span>
								</div>
							</div>
							<div class="shrink-0 text-right text-xs text-muted-foreground">
								<div>{formatDateTime(batch.created_at)}</div>
								<div>{formatDateTime(batch.completed_at)}</div>
								<button onclick={() => viewBatchStatus(batch.id)} class="mt-2 rounded border border-primary/30 px-3 py-1.5 text-xs text-primary hover:bg-primary-light">
									상세보기
								</button>
							</div>
						</div>
					</article>
				{/each}
			</div>
			<div class="hidden bg-white rounded-lg border border-border overflow-x-auto mb-6 md:block">
				<table class="w-full min-w-[600px]">
					<thead class="bg-background border-b border-border">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">ID</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">상태</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">진행</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">생성일</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">완료일</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each batches as batch (batch.id)}
							<tr class="hover:bg-muted">
								<td class="px-4 py-3 text-sm font-medium text-foreground">#{batch.id}</td>
								<td class="px-4 py-3 text-center">
									<span class="px-2 py-1 text-xs rounded-full {getBatchStatusClass(batch.status)}">
										{getBatchStatusLabel(batch.status)}
									</span>
								</td>
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										<div class="flex-1 bg-secondary rounded-full h-2">
											<div
												class="bg-primary h-2 rounded-full transition-all"
												style="width: {batch.progress_percent}%"
											></div>
										</div>
										<span class="text-sm text-muted-foreground w-16 text-right">
											{batch.completed}/{batch.total}
										</span>
									</div>
								</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(batch.created_at)}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(batch.completed_at)}</td>
								<td class="px-4 py-3 text-center">
									<button
										onclick={() => viewBatchStatus(batch.id)}
										class="text-primary hover:text-primary-hover text-sm"
									>
										상세보기
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			{#if batchPager.totalPages > 1}
				<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
					<span class="text-sm text-muted-foreground">
						전체 {batchPager.total}개 중 {(batchPager.page - 1) * batchPager.pageSize + 1} - {Math.min(batchPager.page * batchPager.pageSize, batchPager.total)}
					</span>
					<div class="flex gap-2">
						<Button onclick={batchPrevPage} disabled={batchPager.page === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{batchPager.page} / {batchPager.totalPages}</span>
						<Button onclick={batchNextPage} disabled={batchPager.page >= batchPager.totalPages} variant="secondary" size="sm">
							다음
						</Button>
					</div>
				</div>
			{/if}
		{/if}
	{/if}
</div>

<!-- 배치 상태 모달 -->
{#if activeBatch}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeBatchModal}
		onkeydown={(e) => e.key === 'Escape' && closeBatchModal()}
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
						<h3 class="text-lg font-bold text-foreground">배치 #{activeBatch.id}</h3>
						<span class="px-2 py-1 text-xs rounded-full {getBatchStatusClass(activeBatch.status)}">
							{getBatchStatusLabel(activeBatch.status)}
						</span>
					</div>
					<button onclick={closeBatchModal} class="text-muted-foreground hover:text-muted-foreground text-2xl">
						&times;
					</button>
				</div>

				<!-- 진행 상황 -->
				<div class="mb-6">
					<div class="flex justify-between items-center mb-2">
						<span class="text-sm font-medium text-foreground">진행 상황</span>
						<span class="text-sm text-muted-foreground">
							{activeBatch.completed} 완료 / {activeBatch.failed} 실패 / {activeBatch.total} 전체
						</span>
					</div>
					<div class="w-full bg-secondary rounded-full h-3">
						<div
							class="h-3 rounded-full transition-all {activeBatch.failed > 0 ? 'bg-warning' : 'bg-primary'}"
							style="width: {activeBatch.progress_percent}%"
						></div>
					</div>
					{#if activeBatch.status === 'running' && batchPolling}
						<p class="text-xs text-primary mt-2 animate-pulse">자동 새로고침 중...</p>
					{/if}
				</div>

				<!-- LLM 요청 목록 -->
				<div class="mb-4">
					<h4 class="text-sm font-medium text-foreground mb-2">LLM 요청</h4>
					<div class="max-h-48 overflow-auto border rounded-lg">
						<table class="w-full text-sm">
							<thead class="bg-background sticky top-0">
								<tr>
									<th class="px-3 py-2 text-left text-xs text-muted-foreground">ID</th>
									<th class="px-3 py-2 text-left text-xs text-muted-foreground">타입</th>
									<th class="px-3 py-2 text-center text-xs text-muted-foreground">상태</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-border">
								{#each activeBatch.requests as req}
									<tr class="hover:bg-muted">
										<td class="px-3 py-2 text-foreground">{req.id}</td>
										<td class="px-3 py-2 text-muted-foreground">{req.caller_id.split('_')[0]}</td>
										<td class="px-3 py-2 text-center">
											{#if req.status === 'completed'}
												<span class="text-success"><Check size={14} /></span>
											{:else if req.status === 'failed'}
												<span class="text-error" title={req.error || ''}><X size={14} /></span>
											{:else if req.status === 'processing'}
												<span class="text-primary animate-pulse"><Circle size={10} fill="currentColor" /></span>
											{:else}
												<span class="text-muted-foreground"><Circle size={10} /></span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>

				<!-- 생성된 글 목록 -->
				{#if activeBatch.writings && activeBatch.writings.length > 0}
					<div class="mb-4">
						<h4 class="text-sm font-medium text-foreground mb-2">생성된 글 ({activeBatch.writings.length}개)</h4>
						<div class="space-y-2 max-h-48 overflow-auto">
							{#each activeBatch.writings as writing}
								<div class="p-3 bg-background rounded-lg">
									<div class="flex justify-between items-start mb-1">
										<span class="text-xs px-2 py-0.5 rounded-full {writing.task_type === 'mix' ? 'bg-purple-light text-purple-800' : 'bg-primary-light text-indigo-800'}">
											{getTaskTypeLabel(writing.task_type)}
										</span>
										<span class="text-xs text-muted-foreground">#{writing.id}</span>
									</div>
									<p class="text-sm text-foreground line-clamp-2">{writing.preview}</p>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<div class="flex justify-end pt-4 border-t">
					<Button onclick={closeBatchModal} variant="secondary" size="sm">닫기</Button>
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- 글 상세 모달 -->
{#if showModal && selectedWriting}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeModal}
		onkeydown={(e) => e.key === 'Escape' && closeModal()}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl max-w-3xl w-full max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<div>
						<h3 class="text-lg font-bold text-foreground">글 상세 #{selectedWriting.id}</h3>
						<span class="px-2 py-1 text-xs rounded-full {selectedWriting.task_type === 'mix' ? 'bg-purple-light text-purple-800' : 'bg-primary-light text-indigo-800'}">
							{getTaskTypeLabel(selectedWriting.task_type)}
						</span>
					</div>
					<button onclick={closeModal} class="text-muted-foreground hover:text-muted-foreground text-2xl">
						&times;
					</button>
				</div>

				<div class="grid grid-cols-2 gap-4 text-sm mb-4">
					<div>
						<span class="text-muted-foreground">생성일:</span>
						<span class="ml-1">{formatDateTime(selectedWriting.created_at)}</span>
					</div>
					<div>
						<span class="text-muted-foreground">수정일:</span>
						<span class="ml-1">{formatDateTime(selectedWriting.updated_at)}</span>
					</div>
					<div>
						<span class="text-muted-foreground">소스 ID:</span>
						<span class="ml-1">{selectedWriting.source_ids?.join(', ') || '-'}</span>
					</div>
					<div class="flex items-center">
						<span class="text-muted-foreground">평가:</span>
						<span class="ml-2">
							{#if getRatingComponent(selectedWriting.rating)}
								<svelte:component
									this={getRatingComponent(selectedWriting.rating)}
									size={18}
									class={selectedWriting.rating === 1 ? 'text-success' : 'text-error'}
								/>
							{:else}
								-
							{/if}
						</span>
					</div>
				</div>

				<!-- 평가 버튼 -->
				<div class="mb-4 flex gap-2">
					<Button
						onclick={() => rateWriting(1)}
						variant={selectedWriting.rating === 1 ? 'primary' : 'secondary'}
						size="sm"
						class="flex items-center gap-1"
					>
						<ThumbsUp size={16} /> 추천
					</Button>
					<Button
						onclick={() => rateWriting(-1)}
						variant={selectedWriting.rating === -1 ? 'destructive' : 'secondary'}
						size="sm"
						class="flex items-center gap-1"
					>
						<ThumbsDown size={16} /> 비추천
					</Button>
					{#if selectedWriting.rating !== null}
						<Button
							onclick={() => rateWriting(null)}
							variant="secondary"
							size="sm"
						>
							평가 취소
						</Button>
					{/if}
				</div>

				<!-- 본문 -->
				<div class="mb-4">
					<div class="flex justify-between items-center mb-2">
						<div class="text-sm font-medium text-foreground">본문</div>
						{#if !editMode}
							<button onclick={() => editMode = true} class="text-primary hover:text-primary-hover text-sm">
								수정
							</button>
						{/if}
					</div>
					{#if editMode}
						<textarea
							bind:value={editContent}
							rows="12"
							class="w-full px-3 py-2 border border-border rounded-lg resize-none text-sm"
						></textarea>
						<div class="mt-2 flex gap-2">
							<Button onclick={saveEdit} variant="primary" size="sm">저장</Button>
							<Button onclick={() => { editMode = false; editContent = selectedWriting?.content || ''; }} variant="secondary" size="sm">취소</Button>
						</div>
					{:else}
						<div class="p-4 bg-background rounded-lg whitespace-pre-wrap text-sm max-h-96 overflow-auto">
							{selectedWriting.content}
						</div>
					{/if}
				</div>

				<!-- 프롬프트 (접힘) -->
				{#if selectedWriting.prompt_used}
					<details class="mb-4">
						<summary class="text-sm font-medium text-muted-foreground cursor-pointer hover:text-foreground">
							사용된 프롬프트 보기
						</summary>
						<div class="mt-2 p-3 bg-muted rounded-lg text-xs whitespace-pre-wrap max-h-64 overflow-auto">
							{selectedWriting.prompt_used}
						</div>
					</details>
				{/if}

				<div class="flex gap-2 pt-4 border-t">
					<Button onclick={deleteWriting} variant="destructive" size="sm">삭제</Button>
					<Button onclick={closeModal} variant="secondary" size="sm" class="ml-auto">닫기</Button>
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- 소스 상세 모달 -->
{#if showSourceModal && selectedSource}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeSourceModal}
		onkeydown={(e) => e.key === 'Escape' && closeSourceModal()}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<h3 class="text-lg font-bold text-foreground">소스 #{selectedSource.id}</h3>
					<button onclick={closeSourceModal} class="text-muted-foreground hover:text-muted-foreground text-2xl">
						&times;
					</button>
				</div>

				<div class="grid grid-cols-2 gap-4 text-sm mb-4">
					<div>
						<span class="text-muted-foreground">카테고리:</span>
						<span class="ml-1">{selectedSource.category || '-'}</span>
					</div>
					<div>
						<span class="text-muted-foreground">출처:</span>
						<span class="ml-1">{selectedSource.source_info || '-'}</span>
					</div>
					<div>
						<span class="text-muted-foreground">생성일:</span>
						<span class="ml-1">{formatDateTime(selectedSource.created_at)}</span>
					</div>
				</div>

				<div class="mb-4">
					<div class="text-sm font-medium text-foreground mb-2">내용</div>
					<div class="p-4 bg-background rounded-lg whitespace-pre-wrap text-sm max-h-96 overflow-auto">
						{selectedSource.content}
					</div>
				</div>

				<div class="flex gap-2 pt-4 border-t">
					<Button onclick={deleteSource} variant="destructive" size="sm">삭제</Button>
					<Button onclick={closeSourceModal} variant="secondary" size="sm" class="ml-auto">닫기</Button>
				</div>
			</div>
		</div>
	</div>
{/if}
