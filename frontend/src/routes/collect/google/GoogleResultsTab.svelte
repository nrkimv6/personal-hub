<script lang="ts">
	import { onMount } from 'svelte';
	import type {
		SearchResultListItem,
		SearchResultDetail,
		SearchResultsListResponse,
		DisappearedResultsResponse,
		SearchResultListParams
	} from '$lib/types';
	import { searchResultApi } from '$lib/api/google';
	import { RESULT_FILTER_TABS, type ResultFilterTabValue } from '$lib/constants/searchResultConstants';

	import SearchResultCard from '$lib/components/google/SearchResultCard.svelte';
	import SearchResultTable from '$lib/components/google/SearchResultTable.svelte';
	import SearchResultFilterPanel from '$lib/components/google/SearchResultFilterPanel.svelte';
	import SearchResultDetailModal from '$lib/components/google/SearchResultDetailModal.svelte';

	// 상태
	let results: SearchResultListItem[] = $state([]);
	let total = $state(0);
	let loading = $state(false);
	let error = $state<string | null>(null);

	// 필터 상태
	let activeTab: ResultFilterTabValue = $state('all');
	let query = $state('');
	let search = $state('');
	let dateFrom = $state('');
	let dateTo = $state('');
	let isRead = $state('');
	let sortBy = $state('created_at');
	let sortOrder = $state('desc');
	let page = $state(1);
	let pageSize = $state(20);

	// 모달 상태
	let selectedResult: SearchResultDetail | null = $state(null);
	let isDetailModalOpen = $state(false);

	// 총 페이지 수
	let totalPages = $derived(Math.ceil(total / pageSize));

	// 데이터 로드
	async function loadResults() {
		loading = true;
		error = null;

		try {
			if (activeTab === 'disappeared') {
				const response = await searchResultApi.disappeared({
					query: query || undefined,
					page,
					page_size: pageSize
				});
				results = response.items.map((item) => ({
					id: 0,
					search_id: item.search_id,
					query: item.query,
					rank: item.rank,
					title: item.title || '',
					url: item.url,
					display_url: null,
					snippet: item.snippet,
					publish_date: null,
					page_number: 1,
					is_new: false,
					rank_change: null,
					prev_rank: null,
					is_read: false,
					is_bookmarked: false,
					memo: null,
					created_at: item.created_at,
					saved_search_name: null,
					schedule_name: null
				}));
				total = response.total;
			} else {
				const params: SearchResultListParams = {
					page,
					page_size: pageSize,
					sort_by: sortBy,
					sort_order: sortOrder
				};

				if (query) params.query = query;
				if (search) params.search = search;
				if (dateFrom) params.date_from = dateFrom;
				if (dateTo) params.date_to = dateTo;
				if (isRead !== '') params.is_read = isRead === 'true';

				if (activeTab === 'new') {
					params.is_new = true;
				} else if (activeTab === 'bookmarked') {
					params.is_bookmarked = true;
				}

				const response = await searchResultApi.list(params);
				results = response.items;
				total = response.total;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터를 불러오는데 실패했습니다.';
		} finally {
			loading = false;
		}
	}

	async function handleResultClick(result: SearchResultListItem) {
		if (activeTab === 'disappeared') {
			window.open(result.url, '_blank', 'noopener,noreferrer');
			return;
		}

		try {
			selectedResult = await searchResultApi.get(result.id);
			isDetailModalOpen = true;
		} catch (e) {
			console.error('Failed to load result detail:', e);
		}
	}

	async function handleBookmarkToggle(result: SearchResultListItem, e: MouseEvent) {
		e.stopPropagation();
		try {
			const response = await searchResultApi.toggleBookmark(result.id);
			result.is_bookmarked = response.is_bookmarked;
			results = [...results];
		} catch (e) {
			console.error('Failed to toggle bookmark:', e);
		}
	}

	async function handleReadToggle(result: SearchResultListItem, e: MouseEvent) {
		e.stopPropagation();
		try {
			const response = await searchResultApi.toggleRead(result.id);
			result.is_read = response.is_read;
			results = [...results];
		} catch (e) {
			console.error('Failed to toggle read:', e);
		}
	}

	function handleSort(column: string) {
		if (sortBy === column) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortBy = column;
			sortOrder = column === 'rank' ? 'asc' : 'desc';
		}
		page = 1;
		loadResults();
	}

	function handleTabChange(tab: ResultFilterTabValue) {
		activeTab = tab;
		page = 1;
		loadResults();
	}

	function handleReset() {
		query = '';
		search = '';
		dateFrom = '';
		dateTo = '';
		isRead = '';
		sortBy = 'created_at';
		sortOrder = 'desc';
		page = 1;
		loadResults();
	}

	function handleCloseModal() {
		isDetailModalOpen = false;
		selectedResult = null;
	}

	async function handleModalBookmarkToggle() {
		if (!selectedResult) return;
		try {
			const response = await searchResultApi.toggleBookmark(selectedResult.id);
			selectedResult.is_bookmarked = response.is_bookmarked;

			const idx = results.findIndex((r) => r.id === selectedResult!.id);
			if (idx >= 0) {
				results[idx].is_bookmarked = response.is_bookmarked;
				results = [...results];
			}
		} catch (e) {
			console.error('Failed to toggle bookmark:', e);
		}
	}

	async function handleModalReadToggle() {
		if (!selectedResult) return;
		try {
			const response = await searchResultApi.toggleRead(selectedResult.id);
			selectedResult.is_read = response.is_read;

			const idx = results.findIndex((r) => r.id === selectedResult!.id);
			if (idx >= 0) {
				results[idx].is_read = response.is_read;
				results = [...results];
			}
		} catch (e) {
			console.error('Failed to toggle read:', e);
		}
	}

	async function handleMemoUpdate(memo: string | null) {
		if (!selectedResult) return;
		try {
			const response = await searchResultApi.updateMemo(selectedResult.id, memo);
			selectedResult.memo = response.memo;

			const idx = results.findIndex((r) => r.id === selectedResult!.id);
			if (idx >= 0) {
				results[idx].memo = response.memo;
				results = [...results];
			}
		} catch (e) {
			console.error('Failed to update memo:', e);
		}
	}

	function goToPage(newPage: number) {
		if (newPage < 1 || newPage > totalPages) return;
		page = newPage;
		loadResults();
	}

	let debounceTimer: ReturnType<typeof setTimeout>;
	function debouncedLoad() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			page = 1;
			loadResults();
		}, 300);
	}

	$effect(() => {
		query;
		search;
		debouncedLoad();
	});

	onMount(() => {
		loadResults();
	});
</script>

<div>
	<!-- 헤더 -->
	<div class="flex justify-between items-center mb-6">
		<div>
			<h2 class="text-lg font-bold text-foreground">검색결과 관리</h2>
			<p class="text-sm text-muted-foreground mt-1">
				총 {total.toLocaleString()}개의 검색결과
			</p>
		</div>
	</div>

	<!-- 필터 패널 -->
	<SearchResultFilterPanel
		{activeTab}
		{query}
		{search}
		{dateFrom}
		{dateTo}
		{isRead}
		{sortBy}
		{sortOrder}
		{pageSize}
		onTabChange={handleTabChange}
		onQueryChange={(v) => (query = v)}
		onSearchChange={(v) => (search = v)}
		onDateFromChange={(v) => {
			dateFrom = v;
			page = 1;
			loadResults();
		}}
		onDateToChange={(v) => {
			dateTo = v;
			page = 1;
			loadResults();
		}}
		onReadChange={(v) => {
			isRead = v;
			page = 1;
			loadResults();
		}}
		onSortByChange={(v) => {
			sortBy = v;
			page = 1;
			loadResults();
		}}
		onSortOrderChange={(v) => {
			sortOrder = v;
			page = 1;
			loadResults();
		}}
		onPageSizeChange={(v) => {
			pageSize = v;
			page = 1;
			loadResults();
		}}
		onReset={handleReset}
	/>

	<!-- 로딩/에러 -->
	{#if loading}
		<div class="text-center py-12">
			<div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
			<p class="mt-2 text-muted-foreground">로딩 중...</p>
		</div>
	{:else if error}
		<div class="text-center py-12">
			<p class="text-error">{error}</p>
			<button
				onclick={() => loadResults()}
				class="mt-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
			>
				다시 시도
			</button>
		</div>
	{:else}
		<SearchResultCard
			{results}
			onResultClick={handleResultClick}
			onBookmarkToggle={handleBookmarkToggle}
			onReadToggle={handleReadToggle}
		/>

		<SearchResultTable
			{results}
			{sortBy}
			{sortOrder}
			onResultClick={handleResultClick}
			onBookmarkToggle={handleBookmarkToggle}
			onReadToggle={handleReadToggle}
			onSort={handleSort}
		/>

		<!-- 페이지네이션 -->
		{#if totalPages > 1}
			<div class="flex justify-center items-center gap-2 mt-6">
				<button
					onclick={() => goToPage(page - 1)}
					disabled={page <= 1}
					class="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
					이전
				</button>

				<div class="flex items-center gap-1">
					{#each Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
						let start = Math.max(1, page - 2);
						let end = Math.min(totalPages, start + 4);
						start = Math.max(1, end - 4);
						return start + i;
					}).filter((p) => p <= totalPages) as pageNum}
						<button
							onclick={() => goToPage(pageNum)}
							class="w-8 h-8 text-sm rounded-lg transition-colors {page === pageNum
								? 'bg-primary text-primary-foreground'
								: 'hover:bg-muted'}"
						>
							{pageNum}
						</button>
					{/each}
				</div>

				<button
					onclick={() => goToPage(page + 1)}
					disabled={page >= totalPages}
					class="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
				>
					다음
					<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>
				</button>

				<span class="text-sm text-muted-foreground ml-2">
					{page} / {totalPages} 페이지
				</span>
			</div>
		{/if}
	{/if}
</div>

<!-- 상세 모달 -->
<SearchResultDetailModal
	result={selectedResult}
	isOpen={isDetailModalOpen}
	onClose={handleCloseModal}
	onBookmarkToggle={handleModalBookmarkToggle}
	onReadToggle={handleModalReadToggle}
	onMemoUpdate={handleMemoUpdate}
/>
