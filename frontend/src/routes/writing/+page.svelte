<script lang="ts">
	import { onMount } from 'svelte';
	import { writingApi, keywordApi, type GeneratedWriting, type WritingStats, type WritingSource, type KeywordStats, type KeywordStatsResponse, type Stopword } from '$lib/api';

	// 상태
	let writings: GeneratedWriting[] = [];
	let sources: WritingSource[] = [];
	let stats: WritingStats | null = null;
	let loading = true;
	let error: string | null = null;

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

	// 탭
	type Tab = 'writings' | 'sources' | 'keywords';
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
		if (tab === 'writings') {
			fetchData();
		} else if (tab === 'sources') {
			fetchSources();
		} else if (tab === 'keywords') {
			fetchKeywords();
		}
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
		return type === 'mix' ? '소스 혼합' : type === 'random' ? '랜덤 작문' : type;
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

<div class="p-6">
	<!-- 헤더 -->
	<div class="mb-6 flex justify-between items-center">
		<h2 class="text-2xl font-bold text-gray-900">글쓰기 워커</h2>
		<div class="flex gap-2">
			<button
				onclick={runWritingTask}
				disabled={running}
				class="btn btn-primary btn-sm disabled:opacity-50"
			>
				{running ? '실행 중...' : '수동 실행'}
			</button>
			<button onclick={() => switchTab(activeTab)} class="btn btn-secondary btn-sm">
				새로고침
			</button>
		</div>
	</div>

	<!-- 실행 결과 알림 -->
	{#if runResult}
		<div class="mb-4 p-4 bg-green-50 border border-green-200 text-green-700 rounded-lg">
			실행 완료: 소스 혼합 {runResult.mix_count}개, 랜덤 작문 {runResult.random_count}개 생성됨
			<button onclick={() => runResult = null} class="ml-4 text-green-800 hover:underline">닫기</button>
		</div>
	{/if}

	<!-- 통계 카드 -->
	{#if stats}
		<div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
			<div class="card p-4">
				<div class="text-sm text-gray-500">소스</div>
				<div class="text-2xl font-bold text-gray-900">{stats.source_count}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-gray-500">생성된 글</div>
				<div class="text-2xl font-bold text-blue-600">{stats.generated_count}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-gray-500">소스 혼합</div>
				<div class="text-2xl font-bold text-purple-600">{stats.by_type.mix}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-gray-500">랜덤 작문</div>
				<div class="text-2xl font-bold text-indigo-600">{stats.by_type.random}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-gray-500">오늘 생성</div>
				<div class="text-2xl font-bold text-green-600">{stats.today_count}</div>
			</div>
		</div>
	{/if}

	<!-- 탭 -->
	<div class="mb-4 border-b border-gray-200">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('writings')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'writings' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				생성된 글 ({stats?.generated_count ?? 0})
			</button>
			<button
				onclick={() => switchTab('sources')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'sources' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				소스 ({stats?.source_count ?? 0})
			</button>
			<button
				onclick={() => switchTab('keywords')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'keywords' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				키워드 ({keywordStats?.total_keywords ?? 0})
			</button>
		</nav>
	</div>

	{#if activeTab === 'writings'}
		<!-- 필터 -->
		<div class="mb-4 flex flex-wrap gap-2 items-center">
			<select bind:value={filterTaskType} class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm">
				<option value="">전체 타입</option>
				<option value="mix">소스 혼합</option>
				<option value="random">랜덤 작문</option>
			</select>
			<select bind:value={filterRating} class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm">
				<option value="">전체 평가</option>
				<option value="1">추천</option>
				<option value="-1">비추천</option>
				<option value="null">미평가</option>
			</select>
			<button onclick={handleFilter} class="btn btn-primary btn-sm">필터</button>
			<button onclick={clearFilters} class="btn btn-secondary btn-sm">초기화</button>
		</div>

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
		{:else if writings.length === 0}
			<div class="text-center py-12 text-gray-500">
				<p class="text-lg">생성된 글이 없습니다</p>
				<p class="text-sm mt-2">수동 실행 버튼을 눌러 글을 생성해보세요.</p>
			</div>
		{:else}
			<!-- 글 목록 -->
			<div class="bg-white rounded-lg border border-gray-200 overflow-x-auto mb-6">
				<table class="w-full min-w-[600px]">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">타입</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">미리보기</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">평가</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">생성일</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each writings as writing (writing.id)}
							<tr
								class="hover:bg-gray-50 cursor-pointer"
								onclick={() => openWritingModal(writing)}
							>
								<td class="px-4 py-3 text-sm text-gray-900">{writing.id}</td>
								<td class="px-4 py-3">
									<span class="px-2 py-1 text-xs rounded-full {writing.task_type === 'mix' ? 'bg-purple-100 text-purple-800' : 'bg-indigo-100 text-indigo-800'}">
										{getTaskTypeLabel(writing.task_type)}
									</span>
								</td>
								<td class="px-4 py-3 text-sm text-gray-700 max-w-md truncate">{writing.preview}</td>
								<td class="px-4 py-3 text-lg">{getRatingIcon(writing.rating)}</td>
								<td class="px-4 py-3 text-sm text-gray-500">{formatDateTime(writing.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			{#if pages > 1}
				<div class="flex justify-between items-center">
					<span class="text-sm text-gray-500">
						전체 {total}개 중 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)}
					</span>
					<div class="flex gap-2">
						<button onclick={prevPage} disabled={currentPage === 1} class="btn btn-secondary btn-sm disabled:opacity-50">
							이전
						</button>
						<span class="px-3 py-1.5 text-sm">{currentPage} / {pages}</span>
						<button onclick={nextPage} disabled={currentPage >= pages} class="btn btn-secondary btn-sm disabled:opacity-50">
							다음
						</button>
					</div>
				</div>
			{/if}
		{/if}
	{:else}
		<!-- 소스 목록 -->
		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
		{:else if sources.length === 0}
			<div class="text-center py-12 text-gray-500">
				<p class="text-lg">소스가 없습니다</p>
				<p class="text-sm mt-2">DB에 소스를 추가해주세요.</p>
			</div>
		{:else}
			<div class="bg-white rounded-lg border border-gray-200 overflow-x-auto mb-6">
				<table class="w-full min-w-[500px]">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">카테고리</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">미리보기</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">출처</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">생성일</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each sources as source (source.id)}
							<tr
								class="hover:bg-gray-50 cursor-pointer"
								onclick={() => openSourceModal(source)}
							>
								<td class="px-4 py-3 text-sm text-gray-900">{source.id}</td>
								<td class="px-4 py-3 text-sm text-gray-600">{source.category || '-'}</td>
								<td class="px-4 py-3 text-sm text-gray-700 max-w-md truncate">{source.preview}</td>
								<td class="px-4 py-3 text-sm text-gray-500">{source.source_info || '-'}</td>
								<td class="px-4 py-3 text-sm text-gray-500">{formatDateTime(source.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 소스 페이지네이션 -->
			{#if sourcePages > 1}
				<div class="flex justify-between items-center">
					<span class="text-sm text-gray-500">
						전체 {sourceTotal}개 중 {(sourceCurrentPage - 1) * sourcePageSize + 1} - {Math.min(sourceCurrentPage * sourcePageSize, sourceTotal)}
					</span>
					<div class="flex gap-2">
						<button onclick={sourcePrevPage} disabled={sourceCurrentPage === 1} class="btn btn-secondary btn-sm disabled:opacity-50">
							이전
						</button>
						<span class="px-3 py-1.5 text-sm">{sourceCurrentPage} / {sourcePages}</span>
						<button onclick={sourceNextPage} disabled={sourceCurrentPage >= sourcePages} class="btn btn-secondary btn-sm disabled:opacity-50">
							다음
						</button>
					</div>
				</div>
			{/if}
		{/if}
	{:else if activeTab === 'keywords'}
		<!-- 키워드 통계 -->
		{#if keywordStats}
			<div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
				<div class="card p-4">
					<div class="text-sm text-gray-500">전체 키워드</div>
					<div class="text-2xl font-bold text-gray-900">{keywordStats.total_keywords.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">승격됨</div>
					<div class="text-2xl font-bold text-green-600">{keywordStats.promoted.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">불용어</div>
					<div class="text-2xl font-bold text-red-600">{keywordStats.stopwords.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">검토됨</div>
					<div class="text-2xl font-bold text-blue-600">{keywordStats.reviewed.toLocaleString()}</div>
				</div>
				<div class="card p-4">
					<div class="text-sm text-gray-500">미검토</div>
					<div class="text-2xl font-bold text-orange-600">{keywordStats.pending_review.toLocaleString()}</div>
				</div>
			</div>
		{/if}

		<!-- 분석 결과 알림 -->
		{#if analyzeResult}
			<div class="mb-4 p-4 bg-green-50 border border-green-200 text-green-700 rounded-lg">
				분석 완료 ({analyzeResult.mode}):
				{#if analyzeResult.saved_keywords}
					{analyzeResult.saved_keywords.toLocaleString()}개 키워드 저장
				{:else}
					신규 {analyzeResult.new_keywords ?? 0}개, 업데이트 {analyzeResult.updated_keywords ?? 0}개
				{/if}
				<button onclick={() => analyzeResult = null} class="ml-4 text-green-800 hover:underline">닫기</button>
			</div>
		{/if}

		<!-- 키워드 필터 및 액션 -->
		<div class="mb-4 flex flex-wrap gap-2 items-center justify-between">
			<div class="flex gap-2 items-center">
				<label class="text-sm text-gray-600">최소 빈도:</label>
				<input
					type="number"
					bind:value={keywordMinFreq}
					min="1"
					class="w-20 px-2 py-1 border border-gray-300 rounded text-sm"
				/>
				<button onclick={handleKeywordFilter} class="btn btn-primary btn-sm">필터</button>
			</div>
			<div class="flex gap-2">
				<button
					onclick={() => runAnalysis('incremental')}
					disabled={analyzing}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					{analyzing ? '분석 중...' : '증분 분석'}
				</button>
				<button
					onclick={() => runAnalysis('full')}
					disabled={analyzing}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					전체 분석
				</button>
				<button onclick={promoteBatch} class="btn btn-primary btn-sm">
					일괄 승격
				</button>
			</div>
		</div>

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
		{:else if keywords.length === 0}
			<div class="text-center py-12 text-gray-500">
				<p class="text-lg">키워드가 없습니다</p>
				<p class="text-sm mt-2">분석 버튼을 눌러 키워드를 추출해보세요.</p>
			</div>
		{:else}
			<!-- 키워드 목록 -->
			<div class="bg-white rounded-lg border border-gray-200 overflow-x-auto mb-6">
				<table class="w-full min-w-[700px]">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">키워드</th>
							<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">빈도</th>
							<th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">소스 수</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">상태</th>
							<th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each keywords as kw (kw.id)}
							<tr class="hover:bg-gray-50">
								<td class="px-4 py-3 text-sm font-medium text-gray-900">{kw.keyword}</td>
								<td class="px-4 py-3 text-sm text-right text-gray-700">{kw.frequency.toLocaleString()}</td>
								<td class="px-4 py-3 text-sm text-right text-gray-500">{kw.source_count.toLocaleString()}</td>
								<td class="px-4 py-3 text-center">
									{#if kw.is_promoted}
										<span class="px-2 py-1 text-xs rounded-full bg-green-100 text-green-800">승격됨</span>
									{:else if kw.is_stopword}
										<span class="px-2 py-1 text-xs rounded-full bg-red-100 text-red-800">불용어</span>
									{:else}
										<span class="px-2 py-1 text-xs rounded-full bg-gray-100 text-gray-600">미검토</span>
									{/if}
								</td>
								<td class="px-4 py-3 text-center">
									{#if kw.is_promoted}
										<button
											onclick={() => demoteKeyword(kw)}
											class="text-red-600 hover:text-red-800 text-sm"
										>
											삭제
										</button>
									{:else if !kw.is_stopword}
										<button
											onclick={() => promoteKeyword(kw)}
											class="text-green-600 hover:text-green-800 text-sm mr-2"
										>
											승격
										</button>
										<button
											onclick={() => markAsStopword(kw)}
											class="text-red-600 hover:text-red-800 text-sm"
										>
											불용어
										</button>
									{:else}
										<span class="text-gray-400 text-sm">-</span>
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
					<span class="text-sm text-gray-500">
						전체 {keywordTotal.toLocaleString()}개 중 {keywordOffset + 1} - {Math.min(keywordOffset + keywordLimit, keywordTotal)}
					</span>
					<div class="flex gap-2">
						<button onclick={keywordPrevPage} disabled={keywordOffset === 0} class="btn btn-secondary btn-sm disabled:opacity-50">
							이전
						</button>
						<span class="px-3 py-1.5 text-sm">
							{Math.floor(keywordOffset / keywordLimit) + 1} / {Math.ceil(keywordTotal / keywordLimit)}
						</span>
						<button onclick={keywordNextPage} disabled={keywordOffset + keywordLimit >= keywordTotal} class="btn btn-secondary btn-sm disabled:opacity-50">
							다음
						</button>
					</div>
				</div>
			{/if}
		{/if}
	{/if}
</div>

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
						<h3 class="text-lg font-bold text-gray-900">글 상세 #{selectedWriting.id}</h3>
						<span class="px-2 py-1 text-xs rounded-full {selectedWriting.task_type === 'mix' ? 'bg-purple-100 text-purple-800' : 'bg-indigo-100 text-indigo-800'}">
							{getTaskTypeLabel(selectedWriting.task_type)}
						</span>
					</div>
					<button onclick={closeModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="grid grid-cols-2 gap-4 text-sm mb-4">
					<div>
						<span class="text-gray-500">생성일:</span>
						<span class="ml-1">{formatDateTime(selectedWriting.created_at)}</span>
					</div>
					<div>
						<span class="text-gray-500">수정일:</span>
						<span class="ml-1">{formatDateTime(selectedWriting.updated_at)}</span>
					</div>
					<div>
						<span class="text-gray-500">소스 ID:</span>
						<span class="ml-1">{selectedWriting.source_ids?.join(', ') || '-'}</span>
					</div>
					<div>
						<span class="text-gray-500">평가:</span>
						<span class="ml-1 text-lg">{getRatingIcon(selectedWriting.rating)}</span>
					</div>
				</div>

				<!-- 평가 버튼 -->
				<div class="mb-4 flex gap-2">
					<button
						onclick={() => rateWriting(1)}
						class="btn btn-sm {selectedWriting.rating === 1 ? 'btn-primary' : 'btn-secondary'}"
					>
						👍 추천
					</button>
					<button
						onclick={() => rateWriting(-1)}
						class="btn btn-sm {selectedWriting.rating === -1 ? 'btn-danger' : 'btn-secondary'}"
					>
						👎 비추천
					</button>
					{#if selectedWriting.rating !== null}
						<button
							onclick={() => rateWriting(null)}
							class="btn btn-sm btn-secondary"
						>
							평가 취소
						</button>
					{/if}
				</div>

				<!-- 본문 -->
				<div class="mb-4">
					<div class="flex justify-between items-center mb-2">
						<div class="text-sm font-medium text-gray-700">본문</div>
						{#if !editMode}
							<button onclick={() => editMode = true} class="text-blue-600 hover:text-blue-800 text-sm">
								수정
							</button>
						{/if}
					</div>
					{#if editMode}
						<textarea
							bind:value={editContent}
							rows="12"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg resize-none text-sm"
						></textarea>
						<div class="mt-2 flex gap-2">
							<button onclick={saveEdit} class="btn btn-primary btn-sm">저장</button>
							<button onclick={() => { editMode = false; editContent = selectedWriting?.content || ''; }} class="btn btn-secondary btn-sm">취소</button>
						</div>
					{:else}
						<div class="p-4 bg-gray-50 rounded-lg whitespace-pre-wrap text-sm max-h-96 overflow-auto">
							{selectedWriting.content}
						</div>
					{/if}
				</div>

				<!-- 프롬프트 (접힘) -->
				{#if selectedWriting.prompt_used}
					<details class="mb-4">
						<summary class="text-sm font-medium text-gray-500 cursor-pointer hover:text-gray-700">
							사용된 프롬프트 보기
						</summary>
						<div class="mt-2 p-3 bg-gray-100 rounded-lg text-xs whitespace-pre-wrap max-h-64 overflow-auto">
							{selectedWriting.prompt_used}
						</div>
					</details>
				{/if}

				<div class="flex gap-2 pt-4 border-t">
					<button onclick={deleteWriting} class="btn btn-danger btn-sm">삭제</button>
					<button onclick={closeModal} class="btn btn-secondary btn-sm ml-auto">닫기</button>
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
					<h3 class="text-lg font-bold text-gray-900">소스 #{selectedSource.id}</h3>
					<button onclick={closeSourceModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="grid grid-cols-2 gap-4 text-sm mb-4">
					<div>
						<span class="text-gray-500">카테고리:</span>
						<span class="ml-1">{selectedSource.category || '-'}</span>
					</div>
					<div>
						<span class="text-gray-500">출처:</span>
						<span class="ml-1">{selectedSource.source_info || '-'}</span>
					</div>
					<div>
						<span class="text-gray-500">생성일:</span>
						<span class="ml-1">{formatDateTime(selectedSource.created_at)}</span>
					</div>
				</div>

				<div class="mb-4">
					<div class="text-sm font-medium text-gray-700 mb-2">내용</div>
					<div class="p-4 bg-gray-50 rounded-lg whitespace-pre-wrap text-sm max-h-96 overflow-auto">
						{selectedSource.content}
					</div>
				</div>

				<div class="flex gap-2 pt-4 border-t">
					<button onclick={deleteSource} class="btn btn-danger btn-sm">삭제</button>
					<button onclick={closeSourceModal} class="btn btn-secondary btn-sm ml-auto">닫기</button>
				</div>
			</div>
		</div>
	</div>
{/if}
