<script lang="ts">
	import { onMount } from 'svelte';
	import { writingApi, keywordApi, type GeneratedWriting, type WritingStats, type WritingSource, type KeywordStats, type KeywordStatsResponse, type Stopword, type WritingElement, type WritingElementStats, type WritingBatch, type WritingBatchStatus } from '$lib/api';
	import { Button } from '$lib/components/ui';

	// 상태
	let writings: GeneratedWriting[] = [];
	let sources: WritingSource[] = [];
	let stats: WritingStats | null = null;
	let loading = true;
	let error: string | null = null;

	// 배치 상태
	let batches: WritingBatch[] = [];
	let batchTotal = 0;
	let batchPage = 1;
	let batchPageSize = 10;
	let batchPages = 0;
	let activeBatch: WritingBatchStatus | null = null;
	let batchPolling: ReturnType<typeof setInterval> | null = null;
	let creatingBatch = false;

	// 키워드 상태
	let keywords: KeywordStats[] = [];
	let keywordStats: KeywordStatsResponse | null = null;
	let stopwords: Stopword[] = [];
	let keywordOffset = 0;
	let keywordLimit = 100;
	let keywordTotal = 0;
	let keywordMinFreq = 10;
	let analyzing = false;
	let analyzeResult: { mode: string; saved_keywords?: number; new_keywords?: number; updated_keywords?: number } | null = null;

	// 소재 상태
	let elements: WritingElement[] = [];
	let elementStats: WritingElementStats | null = null;
	let elementCurrentPage = 1;
	let elementPageSize = 50;
	let elementTotal = 0;
	let elementPages = 0;
	let elementFilterCategory = '';
	let elementFilterSourceType = '';
	let extracting = false;
	let extractResult: { success: boolean; created_requests: number } | null = null;

	// 탭
	type Tab = 'writings' | 'sources' | 'keywords' | 'elements' | 'batches';
	let activeTab: Tab = 'writings';

	// 필터
	let filterTaskType = '';
	let filterRating = '';

	// 페이지네이션
	let currentPage = 1;
	let pageSize = 20;
	let total = 0;
	let pages = 0;

	// 소스 페이지네이션
	let sourceCurrentPage = 1;
	let sourcePageSize = 50;
	let sourceTotal = 0;
	let sourcePages = 0;

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

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const [listRes, statsRes] = await Promise.all([
				writingApi.listGenerated({
					task_type: filterTaskType || undefined,
					rating: filterRating || undefined,
					page: currentPage,
					page_size: pageSize
				}),
				writingApi.getStats()
			]);

			writings = listRes.items;
			total = listRes.total;
			pages = listRes.pages;
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
				page: sourceCurrentPage,
				page_size: sourcePageSize
			});
			sources = res.items;
			sourceTotal = res.total;
			sourcePages = res.pages;
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
					page: elementCurrentPage,
					page_size: elementPageSize
				}),
				writingApi.getElementsStats()
			]);
			elements = listRes.items;
			elementTotal = listRes.total;
			elementPages = listRes.pages;
			elementStats = statsRes;
		} catch (e) {
			error = e instanceof Error ? e.message : '소재 로드 실패';
		} finally {
			loading = false;
		}
	}

	function handleElementFilter() {
		elementCurrentPage = 1;
		fetchElements();
	}

	function elementPrevPage() {
		if (elementCurrentPage > 1) {
			elementCurrentPage--;
			fetchElements();
		}
	}

	function elementNextPage() {
		if (elementCurrentPage < elementPages) {
			elementCurrentPage++;
			fetchElements();
		}
	}

	async function deleteElement(id: number, name: string) {
		if (!confirm(`"${name}" 소재를 삭제하시겠습니까?`)) return;
		try {
			await writingApi.deleteElement(id);
			await fetchElements();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function extractTopics() {
		if (extracting) return;
		const limitStr = prompt('추출할 소스 수 (기본: 100, 최대: 500)', '100');
		if (!limitStr) return;
		const limit = parseInt(limitStr);
		if (isNaN(limit) || limit < 1 || limit > 500) {
			alert('1~500 사이의 숫자를 입력하세요.');
			return;
		}

		extracting = true;
		extractResult = null;
		try {
			const result = await writingApi.extractTopics(limit);
			extractResult = result;
			alert(`${result.created_requests}개의 추출 요청이 생성되었습니다. Claude Worker가 처리합니다.`);
		} catch (e) {
			alert('추출 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
					limit: keywordLimit,
					offset: keywordOffset,
					min_frequency: keywordMinFreq,
					include_stopwords: false,
					include_promoted: true
				}),
				keywordApi.stats()
			]);
			keywords = listRes.items;
			keywordTotal = listRes.total;
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
		if (!confirm(confirmMsg)) return;

		analyzing = true;
		analyzeResult = null;
		try {
			const result = await keywordApi.analyze({ mode });
			analyzeResult = result;
			await fetchKeywords();
		} catch (e) {
			alert('분석 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			analyzing = false;
		}
	}

	async function promoteKeyword(kw: KeywordStats) {
		if (!confirm(`"${kw.keyword}"를 writing_elements로 승격하시겠습니까?`)) return;
		try {
			await keywordApi.promote(kw.id);
			alert(`"${kw.keyword}" 승격 완료`);
			await fetchKeywords();
		} catch (e) {
			alert('승격 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function demoteKeyword(kw: KeywordStats) {
		if (!confirm(`"${kw.keyword}" 승격을 취소하시겠습니까?`)) return;
		try {
			await keywordApi.demote(kw.id);
			alert(`"${kw.keyword}" 승격 취소 완료`);
			await fetchKeywords();
		} catch (e) {
			alert('승격 취소 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function markAsStopword(kw: KeywordStats) {
		if (!confirm(`"${kw.keyword}"를 불용어로 마킹하시겠습니까?`)) return;
		try {
			await keywordApi.markStopword(kw.id);
			alert(`"${kw.keyword}" 불용어 처리 완료`);
			await fetchKeywords();
		} catch (e) {
			alert('불용어 마킹 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
			alert(`${result.promoted_count}개 키워드가 승격되었습니다.`);
			await fetchKeywords();
		} catch (e) {
			alert('일괄 승격 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	function keywordPrevPage() {
		if (keywordOffset > 0) {
			keywordOffset = Math.max(0, keywordOffset - keywordLimit);
			fetchKeywords();
		}
	}

	function keywordNextPage() {
		if (keywordOffset + keywordLimit < keywordTotal) {
			keywordOffset += keywordLimit;
			fetchKeywords();
		}
	}

	function handleKeywordFilter() {
		keywordOffset = 0;
		fetchKeywords();
	}

	function handleFilter() {
		currentPage = 1;
		fetchData();
	}

	function clearFilters() {
		filterTaskType = '';
		filterRating = '';
		handleFilter();
	}

	function prevPage() {
		if (currentPage > 1) {
			currentPage--;
			fetchData();
		}
	}

	function nextPage() {
		if (currentPage < pages) {
			currentPage++;
			fetchData();
		}
	}

	function sourcePrevPage() {
		if (sourceCurrentPage > 1) {
			sourceCurrentPage--;
			fetchSources();
		}
	}

	function sourceNextPage() {
		if (sourceCurrentPage < sourcePages) {
			sourceCurrentPage++;
			fetchSources();
		}
	}

	async function openWritingModal(writing: GeneratedWriting) {
		try {
			const full = await writingApi.getGenerated(writing.id);
			selectedWriting = full;
			editContent = full.content;
			editMode = false;
			showModal = true;
		} catch (e) {
			alert('상세 조회 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
			alert('소스 조회 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
			alert('저장되었습니다.');
			editMode = false;
			await fetchData();
			// 모달 내용 업데이트
			const updated = await writingApi.getGenerated(selectedWriting.id);
			selectedWriting = updated;
		} catch (e) {
			alert('저장 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function rateWriting(rating: number | null) {
		if (!selectedWriting) return;
		try {
			await writingApi.rateGenerated(selectedWriting.id, rating);
			selectedWriting.rating = rating;
			await fetchData();
		} catch (e) {
			alert('평가 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function deleteWriting() {
		if (!selectedWriting) return;
		if (!confirm('이 글을 삭제하시겠습니까?')) return;
		try {
			await writingApi.deleteGenerated(selectedWriting.id);
			closeModal();
			await fetchData();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function deleteSource() {
		if (!selectedSource) return;
		if (!confirm('이 소스를 삭제하시겠습니까?')) return;
		try {
			await writingApi.deleteSource(selectedSource.id);
			closeSourceModal();
			await fetchSources();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function runWritingTask() {
		if (running) return;
		if (!confirm('작문 태스크를 수동 실행하시겠습니까? (mix 5개 + random 3개)')) return;

		running = true;
		runResult = null;
		try {
			const result = await writingApi.run();
			runResult = result;
			await fetchData();
		} catch (e) {
			alert('실행 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
				page: batchPage,
				page_size: batchPageSize
			});
			batches = res.items;
			batchTotal = res.total;
			batchPages = res.pages;
		} catch (e) {
			error = e instanceof Error ? e.message : '배치 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function createBatch() {
		if (creatingBatch) return;
		if (!confirm('새 글쓰기 배치를 생성하시겠습니까? (11개 LLM 요청)')) return;

		creatingBatch = true;
		try {
			const result = await writingApi.createBatch();
			alert(result.message);
			await fetchBatches();
			// 생성 후 바로 해당 배치 상태 확인
			await viewBatchStatus(result.batch_id);
		} catch (e) {
			alert('배치 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
			alert('배치 상태 조회 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
		if (batchPage > 1) {
			batchPage--;
			fetchBatches();
		}
	}

	function batchNextPage() {
		if (batchPage < batchPages) {
			batchPage++;
			fetchBatches();
		}
	}

	function getRatingIcon(rating: number | null): string {
		if (rating === 1) return '👍';
		if (rating === -1) return '👎';
		return '-';
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
				on:click={runWritingTask}
				disabled={running}
				variant="primary"
				size="sm"
			>
				{running ? '실행 중...' : '수동 실행'}
			</Button>
			<Button on:click={() => switchTab(activeTab)} variant="secondary" size="sm">
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
	<div class="mb-4 border-b border-border">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('writings')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'writings' ? 'border-blue-600 text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				생성된 글 ({stats?.generated_count ?? 0})
			</button>
			<button
				onclick={() => switchTab('sources')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'sources' ? 'border-blue-600 text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				소스 ({stats?.source_count ?? 0})
			</button>
			<button
				onclick={() => switchTab('keywords')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'keywords' ? 'border-blue-600 text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				키워드 ({keywordStats?.total_keywords ?? 0})
			</button>
			<button
				onclick={() => switchTab('elements')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'elements' ? 'border-blue-600 text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				소재 ({elementStats?.total ?? 0})
			</button>
			<button
				onclick={() => switchTab('batches')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'batches' ? 'border-blue-600 text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				배치 ({batchTotal})
			</button>
		</nav>
	</div>

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
			<Button on:click={handleFilter} variant="primary" size="sm">필터</Button>
			<Button on:click={clearFilters} variant="secondary" size="sm">초기화</Button>
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
			<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
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
								<td class="px-4 py-3 text-lg">{getRatingIcon(writing.rating)}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(writing.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			{#if pages > 1}
				<div class="flex justify-between items-center">
					<span class="text-sm text-muted-foreground">
						전체 {total}개 중 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)}
					</span>
					<div class="flex gap-2">
						<Button on:click={prevPage} disabled={currentPage === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{currentPage} / {pages}</span>
						<Button on:click={nextPage} disabled={currentPage >= pages} variant="secondary" size="sm">
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
			<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
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
			{#if sourcePages > 1}
				<div class="flex justify-between items-center">
					<span class="text-sm text-muted-foreground">
						전체 {sourceTotal}개 중 {(sourceCurrentPage - 1) * sourcePageSize + 1} - {Math.min(sourceCurrentPage * sourcePageSize, sourceTotal)}
					</span>
					<div class="flex gap-2">
						<Button on:click={sourcePrevPage} disabled={sourceCurrentPage === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{sourceCurrentPage} / {sourcePages}</span>
						<Button on:click={sourceNextPage} disabled={sourceCurrentPage >= sourcePages} variant="secondary" size="sm">
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
				<Button on:click={handleKeywordFilter} variant="primary" size="sm">필터</Button>
			</div>
			<div class="flex gap-2">
				<Button
					on:click={() => runAnalysis('incremental')}
					disabled={analyzing}
					variant="secondary"
					size="sm"
				>
					{analyzing ? '분석 중...' : '증분 분석'}
				</Button>
				<Button
					on:click={() => runAnalysis('full')}
					disabled={analyzing}
					variant="secondary"
					size="sm"
				>
					전체 분석
				</Button>
				<Button on:click={promoteBatch} variant="primary" size="sm">
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
			<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
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
			{#if keywordTotal > keywordLimit}
				<div class="flex justify-between items-center">
					<span class="text-sm text-muted-foreground">
						전체 {keywordTotal.toLocaleString()}개 중 {keywordOffset + 1} - {Math.min(keywordOffset + keywordLimit, keywordTotal)}
					</span>
					<div class="flex gap-2">
						<Button on:click={keywordPrevPage} disabled={keywordOffset === 0} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">
							{Math.floor(keywordOffset / keywordLimit) + 1} / {Math.ceil(keywordTotal / keywordLimit)}
						</span>
						<Button on:click={keywordNextPage} disabled={keywordOffset + keywordLimit >= keywordTotal} variant="secondary" size="sm">
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
				<Button on:click={handleElementFilter} variant="primary" size="sm">필터</Button>
			</div>
			<Button
				on:click={extractTopics}
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
			<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
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
			{#if elementPages > 1}
				<div class="flex justify-between items-center">
					<span class="text-sm text-muted-foreground">
						전체 {elementTotal}개 중 {(elementCurrentPage - 1) * elementPageSize + 1} - {Math.min(elementCurrentPage * elementPageSize, elementTotal)}
					</span>
					<div class="flex gap-2">
						<Button on:click={elementPrevPage} disabled={elementCurrentPage === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{elementCurrentPage} / {elementPages}</span>
						<Button on:click={elementNextPage} disabled={elementCurrentPage >= elementPages} variant="secondary" size="sm">
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
				on:click={createBatch}
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
			<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
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
			{#if batchPages > 1}
				<div class="flex justify-between items-center">
					<span class="text-sm text-muted-foreground">
						전체 {batchTotal}개 중 {(batchPage - 1) * batchPageSize + 1} - {Math.min(batchPage * batchPageSize, batchTotal)}
					</span>
					<div class="flex gap-2">
						<Button on:click={batchPrevPage} disabled={batchPage === 1} variant="secondary" size="sm">
							이전
						</Button>
						<span class="px-3 py-1.5 text-sm">{batchPage} / {batchPages}</span>
						<Button on:click={batchNextPage} disabled={batchPage >= batchPages} variant="secondary" size="sm">
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
												<span class="text-success">✓</span>
											{:else if req.status === 'failed'}
												<span class="text-error" title={req.error || ''}>✗</span>
											{:else if req.status === 'processing'}
												<span class="text-primary animate-pulse">●</span>
											{:else}
												<span class="text-muted-foreground">○</span>
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
					<Button on:click={closeBatchModal} variant="secondary" size="sm">닫기</Button>
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
					<div>
						<span class="text-muted-foreground">평가:</span>
						<span class="ml-1 text-lg">{getRatingIcon(selectedWriting.rating)}</span>
					</div>
				</div>

				<!-- 평가 버튼 -->
				<div class="mb-4 flex gap-2">
					<Button
						on:click={() => rateWriting(1)}
						variant={selectedWriting.rating === 1 ? 'primary' : 'secondary'}
						size="sm"
					>
						👍 추천
					</Button>
					<Button
						on:click={() => rateWriting(-1)}
						variant={selectedWriting.rating === -1 ? 'destructive' : 'secondary'}
						size="sm"
					>
						👎 비추천
					</Button>
					{#if selectedWriting.rating !== null}
						<Button
							on:click={() => rateWriting(null)}
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
							<Button on:click={saveEdit} variant="primary" size="sm">저장</Button>
							<Button on:click={() => { editMode = false; editContent = selectedWriting?.content || ''; }} variant="secondary" size="sm">취소</Button>
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
					<Button on:click={deleteWriting} variant="destructive" size="sm">삭제</Button>
					<Button on:click={closeModal} variant="secondary" size="sm" class="ml-auto">닫기</Button>
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
					<Button on:click={deleteSource} variant="destructive" size="sm">삭제</Button>
					<Button on:click={closeSourceModal} variant="secondary" size="sm" class="ml-auto">닫기</Button>
				</div>
			</div>
		</div>
	</div>
{/if}
