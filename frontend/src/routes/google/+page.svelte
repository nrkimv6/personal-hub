<script lang="ts">
	import { onMount } from 'svelte';

	// 타입 정의
	interface SearchResult {
		rank: number;
		title: string;
		url: string;
		display_url?: string;
		snippet?: string;
		publish_date?: string;
	}

	interface SavedSearch {
		id: number;
		name: string;
		query: string;
		date_filter?: string;
		max_pages: number;
		account_id?: number;
		is_favorite: boolean;
		last_search_id?: string;
		last_run_at?: string;
		last_result_count?: number;
		created_at: string;
		updated_at: string;
	}

	interface SearchHistoryItem {
		search_id: string;
		query: string;
		date_filter?: string;
		status: string;
		total_results: number;
		created_at: string;
	}

	// API 함수
	const API_BASE = '/api/google';

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
	let query = $state('');
	let dateFilter = $state('');
	let maxPages = $state(1);
	let loading = $state(false);
	let results: SearchResult[] = $state([]);
	let error = $state('');

	let savedSearches: SavedSearch[] = $state([]);
	let history: SearchHistoryItem[] = $state([]);
	let showSaveModal = $state(false);
	let saveName = $state('');
	let saveAsFavorite = $state(false);

	let activeTab: 'saved' | 'history' = $state('saved');

	const dateFilters = [
		{ value: '', label: '전체 기간' },
		{ value: '1h', label: '최근 1시간' },
		{ value: '24h', label: '최근 24시간' },
		{ value: '1w', label: '최근 1주일' },
		{ value: '1m', label: '최근 1개월' },
		{ value: '1y', label: '최근 1년' }
	];

	// 검색 기능
	async function search() {
		if (!query.trim()) return;

		loading = true;
		error = '';

		try {
			const response = await apiRequest<{
				search_id: string;
				query: string;
				status: string;
				total_results: number;
				results: SearchResult[];
			}>('/search', {
				method: 'POST',
				body: JSON.stringify({
					query: query.trim(),
					date_filter: dateFilter || undefined,
					max_pages: maxPages
				})
			});
			results = response.results;
			await loadHistory();
		} catch (e) {
			error = e instanceof Error ? e.message : '검색 중 오류가 발생했습니다.';
		} finally {
			loading = false;
		}
	}

	// 저장된 검색 기능
	async function loadSavedSearches() {
		try {
			savedSearches = await apiRequest<SavedSearch[]>('/saved');
		} catch (e) {
			console.error('저장된 검색 로드 실패:', e);
		}
	}

	async function saveCurrentSearch() {
		if (!saveName.trim() || !query.trim()) return;

		try {
			await apiRequest('/saved', {
				method: 'POST',
				body: JSON.stringify({
					name: saveName.trim(),
					query: query.trim(),
					date_filter: dateFilter || undefined,
					max_pages: maxPages,
					is_favorite: saveAsFavorite
				})
			});
			showSaveModal = false;
			saveName = '';
			saveAsFavorite = false;
			await loadSavedSearches();
		} catch (e) {
			error = '저장 실패';
		}
	}

	async function runSavedSearch(saved: SavedSearch) {
		loading = true;
		error = '';

		try {
			const response = await apiRequest<{
				search_id: string;
				results: SearchResult[];
			}>(`/saved/${saved.id}/run`, { method: 'POST' });
			results = response.results;
			query = saved.query;
			dateFilter = saved.date_filter || '';
			maxPages = saved.max_pages;
			await loadSavedSearches();
		} catch (e) {
			error = e instanceof Error ? e.message : '검색 실패';
		} finally {
			loading = false;
		}
	}

	async function toggleFavorite(saved: SavedSearch, event: Event) {
		event.stopPropagation();
		try {
			await apiRequest(`/saved/${saved.id}/toggle-favorite`, { method: 'POST' });
			await loadSavedSearches();
		} catch (e) {
			console.error('즐겨찾기 토글 실패:', e);
		}
	}

	async function deleteSavedSearch(saved: SavedSearch, event: Event) {
		event.stopPropagation();
		if (!confirm(`"${saved.name}" 검색 조건을 삭제하시겠습니까?`)) return;

		try {
			await apiRequest(`/saved/${saved.id}`, { method: 'DELETE' });
			await loadSavedSearches();
		} catch (e) {
			error = '삭제 실패';
		}
	}

	async function loadLastResults(saved: SavedSearch, event: Event) {
		event.stopPropagation();
		if (!saved.last_search_id) return;

		try {
			const response = await apiRequest<{ results: SearchResult[] }>(
				`/results/${saved.last_search_id}`
			);
			results = response.results;
			query = saved.query;
			dateFilter = saved.date_filter || '';
		} catch (e) {
			error = '결과 로드 실패';
		}
	}

	// 히스토리 기능
	async function loadHistory() {
		try {
			history = await apiRequest<SearchHistoryItem[]>('/history');
		} catch (e) {
			console.error('히스토리 로드 실패:', e);
		}
	}

	async function loadFromHistory(item: SearchHistoryItem) {
		try {
			const response = await apiRequest<{ results: SearchResult[] }>(`/results/${item.search_id}`);
			results = response.results;
			query = item.query;
			dateFilter = item.date_filter || '';
		} catch (e) {
			error = '결과 로드 실패';
		}
	}

	function formatDate(dateStr: string | undefined): string {
		if (!dateStr) return '';
		return new Date(dateStr).toLocaleString('ko-KR', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function handleKeypress(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			search();
		}
	}

	onMount(() => {
		loadSavedSearches();
		loadHistory();
	});
</script>

<svelte:head>
	<title>구글 검색 | Monitor Page</title>
</svelte:head>

<div class="container mx-auto p-4">
	<h1 class="mb-6 text-2xl font-bold">구글 검색</h1>

	<!-- 검색 폼 -->
	<div class="mb-6 rounded-lg bg-white p-4 shadow">
		<div class="flex flex-wrap gap-4">
			<input
				type="text"
				bind:value={query}
				placeholder="검색어 입력..."
				class="min-w-64 flex-1 rounded-lg border px-4 py-2"
				onkeypress={handleKeypress}
			/>

			<select bind:value={dateFilter} class="rounded-lg border px-4 py-2">
				{#each dateFilters as filter}
					<option value={filter.value}>{filter.label}</option>
				{/each}
			</select>

			<select bind:value={maxPages} class="rounded-lg border px-4 py-2">
				{#each [1, 2, 3, 5, 10] as pages}
					<option value={pages}>{pages} 페이지</option>
				{/each}
			</select>

			<button
				onclick={search}
				disabled={loading || !query.trim()}
				class="rounded-lg bg-blue-500 px-6 py-2 text-white hover:bg-blue-600 disabled:opacity-50"
			>
				{loading ? '검색 중...' : '검색'}
			</button>

			<button
				onclick={() => (showSaveModal = true)}
				disabled={!query.trim()}
				class="rounded-lg border border-gray-300 px-4 py-2 hover:bg-gray-50 disabled:opacity-50"
				title="검색 조건 저장"
			>
				저장
			</button>
		</div>
	</div>

	{#if error}
		<div class="mb-6 rounded-lg bg-red-100 p-4 text-red-700">{error}</div>
	{/if}

	<div class="grid grid-cols-1 gap-6 lg:grid-cols-4">
		<!-- 검색 결과 -->
		<div class="lg:col-span-3">
			<h2 class="mb-4 text-lg font-semibold">검색 결과 ({results.length}개)</h2>

			{#if results.length === 0}
				<div class="text-gray-500">검색 결과가 없습니다.</div>
			{:else}
				<div class="space-y-4">
					{#each results as result}
						<div class="rounded-lg bg-white p-4 shadow">
							<div class="flex items-start gap-3">
								<span class="w-6 font-mono text-sm text-gray-400">{result.rank}</span>
								<div class="flex-1">
									<a
										href={result.url}
										target="_blank"
										rel="noopener noreferrer"
										class="font-medium text-blue-600 hover:underline"
									>
										{result.title}
									</a>
									{#if result.display_url}
										<div class="mt-1 text-sm text-green-700">{result.display_url}</div>
									{/if}
									{#if result.snippet}
										<p class="mt-2 text-sm text-gray-600">{result.snippet}</p>
									{/if}
									{#if result.publish_date}
										<span class="mt-2 inline-block text-xs text-gray-400">
											{result.publish_date}
										</span>
									{/if}
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- 사이드바: 저장된 검색 + 히스토리 -->
		<div>
			<!-- 탭 헤더 -->
			<div class="mb-4 flex border-b">
				<button
					onclick={() => (activeTab = 'saved')}
					class="flex-1 border-b-2 py-2 text-sm font-medium transition-colors"
					class:border-blue-500={activeTab === 'saved'}
					class:text-blue-600={activeTab === 'saved'}
					class:border-transparent={activeTab !== 'saved'}
					class:text-gray-500={activeTab !== 'saved'}
				>
					저장된 검색
				</button>
				<button
					onclick={() => (activeTab = 'history')}
					class="flex-1 border-b-2 py-2 text-sm font-medium transition-colors"
					class:border-blue-500={activeTab === 'history'}
					class:text-blue-600={activeTab === 'history'}
					class:border-transparent={activeTab !== 'history'}
					class:text-gray-500={activeTab !== 'history'}
				>
					최근 검색
				</button>
			</div>

			<!-- 저장된 검색 목록 -->
			{#if activeTab === 'saved'}
				<div class="rounded-lg bg-white shadow">
					{#if savedSearches.length === 0}
						<div class="p-4 text-sm text-gray-500">저장된 검색이 없습니다.</div>
					{:else}
						<ul class="divide-y">
							{#each savedSearches as saved}
								<li class="hover:bg-gray-50">
									<div class="p-3">
										<div class="flex items-center justify-between">
											<button onclick={() => runSavedSearch(saved)} class="flex-1 text-left">
												<div class="flex items-center gap-2">
													{#if saved.is_favorite}
														<span class="text-yellow-500">★</span>
													{/if}
													<span class="text-sm font-medium">{saved.name}</span>
												</div>
												<div class="mt-1 text-xs text-gray-500">{saved.query}</div>
											</button>

											<!-- 액션 버튼 -->
											<div class="flex gap-1">
												<button
													onclick={(e) => toggleFavorite(saved, e)}
													class="p-1 text-gray-400 hover:text-yellow-500"
													title="즐겨찾기"
												>
													{saved.is_favorite ? '★' : '☆'}
												</button>
												{#if saved.last_search_id}
													<button
														onclick={(e) => loadLastResults(saved, e)}
														class="p-1 text-xs text-gray-400 hover:text-blue-500"
														title="마지막 결과 보기"
													>
														📋
													</button>
												{/if}
												<button
													onclick={(e) => deleteSavedSearch(saved, e)}
													class="p-1 text-gray-400 hover:text-red-500"
													title="삭제"
												>
													✕
												</button>
											</div>
										</div>

										<!-- 메타 정보 -->
										<div class="mt-2 flex gap-2 text-xs text-gray-400">
											{#if saved.date_filter}
												<span
													>{dateFilters.find((f) => f.value === saved.date_filter)?.label}</span
												>
											{/if}
											<span>{saved.max_pages}p</span>
											{#if saved.last_run_at}
												<span>· {formatDate(saved.last_run_at)}</span>
											{/if}
											{#if saved.last_result_count}
												<span>({saved.last_result_count}개)</span>
											{/if}
										</div>
									</div>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/if}

			<!-- 검색 히스토리 -->
			{#if activeTab === 'history'}
				<div class="rounded-lg bg-white shadow">
					{#if history.length === 0}
						<div class="p-4 text-sm text-gray-500">검색 기록이 없습니다.</div>
					{:else}
						<ul class="divide-y">
							{#each history as item}
								<li>
									<button
										onclick={() => loadFromHistory(item)}
										class="w-full p-3 text-left hover:bg-gray-50"
									>
										<div class="text-sm font-medium">{item.query}</div>
										<div class="mt-1 text-xs text-gray-400">
											{item.total_results}개 결과
											{#if item.date_filter}
												· {dateFilters.find((f) => f.value === item.date_filter)?.label}
											{/if}
										</div>
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>

<!-- 저장 모달 -->
{#if showSaveModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
		<div class="w-96 rounded-lg bg-white p-6 shadow-xl">
			<h3 class="mb-4 text-lg font-semibold">검색 조건 저장</h3>

			<div class="space-y-4">
				<div>
					<label for="save-name" class="mb-1 block text-sm font-medium">저장 이름</label>
					<input
						id="save-name"
						type="text"
						bind:value={saveName}
						placeholder="예: Python 블로그 검색"
						class="w-full rounded-lg border px-3 py-2"
					/>
				</div>

				<div class="text-sm text-gray-600">
					<div><strong>검색어:</strong> {query}</div>
					<div>
						<strong>날짜 필터:</strong>
						{dateFilters.find((f) => f.value === dateFilter)?.label || '전체'}
					</div>
					<div><strong>페이지 수:</strong> {maxPages}</div>
				</div>

				<label class="flex items-center gap-2">
					<input type="checkbox" bind:checked={saveAsFavorite} />
					<span class="text-sm">즐겨찾기에 추가</span>
				</label>
			</div>

			<div class="mt-6 flex justify-end gap-2">
				<button
					onclick={() => (showSaveModal = false)}
					class="rounded-lg px-4 py-2 text-gray-600 hover:bg-gray-100"
				>
					취소
				</button>
				<button
					onclick={saveCurrentSearch}
					disabled={!saveName.trim()}
					class="rounded-lg bg-blue-500 px-4 py-2 text-white hover:bg-blue-600 disabled:opacity-50"
				>
					저장
				</button>
			</div>
		</div>
	</div>
{/if}
