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
		service_account_id?: number;
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

	interface Schedule {
		id: number;
		name: string;
		display_name?: string;
		target_config: { saved_search_id: number };
		schedule_value: {
			time_windows: { start: string; end: string }[];
			daily_runs: number;
			min_interval_hours: number;
		};
		enabled: boolean;
		next_run_at?: string;
		last_run_at?: string;
	}

	interface ScheduleRun {
		id: number;
		started_at: string;
		finished_at?: string;
		status: string;
		collected_count: number;
		stop_reason?: string;
		error_message?: string;
	}

	// API 함수
	const API_BASE = '/api/v1/google';

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

	// 스케줄 상태
	let schedules: Schedule[] = $state([]);
	let showScheduleModal = $state(false);
	let selectedSavedSearch: SavedSearch | null = $state(null);
	let scheduleTime = $state('09:00');
	let scheduleEnabled = $state(true);
	let editingSchedule: Schedule | null = $state(null);
	let showRunsModal = $state(false);
	let scheduleRuns: ScheduleRun[] = $state([]);
	let selectedScheduleId: number | null = $state(null);

	const dateFilters = [
		{ value: '', label: '전체 기간' },
		{ value: '1h', label: '최근 1시간' },
		{ value: '24h', label: '최근 24시간' },
		{ value: '1w', label: '최근 1주일' },
		{ value: '1m', label: '최근 1개월' },
		{ value: '1y', label: '최근 1년' }
	];

	// 현재 폴링 중인 검색 ID
	let pendingSearchId: string | null = $state(null);

	// 검색 기능 (비동기 폴링 방식)
	async function search() {
		if (!query.trim()) return;

		loading = true;
		error = '';
		results = [];

		try {
			// 1. 검색 요청을 큐에 추가
			const queueResponse = await apiRequest<{
				search_id: string;
				status: string;
				message: string;
			}>('/search', {
				method: 'POST',
				body: JSON.stringify({
					query: query.trim(),
					date_filter: dateFilter || undefined,
					max_pages: maxPages
				})
			});

			// 2. 상태 폴링하여 완료될 때까지 대기
			const searchId = queueResponse.search_id;
			pendingSearchId = searchId;
			await pollForResults(searchId);
		} catch (e) {
			error = e instanceof Error ? e.message : '검색 중 오류가 발생했습니다.';
		} finally {
			loading = false;
			pendingSearchId = null;
		}
	}

	// 검색 결과 폴링 (무제한, 1초 간격)
	async function pollForResults(searchId: string) {
		let status = 'pending';

		while (status === 'pending' || status === 'processing') {
			// 다른 검색이 시작되면 현재 폴링 중단
			if (pendingSearchId !== searchId) {
				return;
			}

			await new Promise((resolve) => setTimeout(resolve, 1000)); // 1초 대기

			try {
				const statusResponse = await apiRequest<{
					search_id: string;
					query: string;
					status: string;
					total_results: number;
					error_message?: string;
					results: SearchResult[];
				}>(`/search/${searchId}/status`);

				status = statusResponse.status;

				if (status === 'completed') {
					results = statusResponse.results;
					await loadHistory();
					break;
				} else if (status === 'failed') {
					throw new Error(statusResponse.error_message || '검색 실패');
				}
			} catch (e) {
				// 네트워크 에러 시 재시도
				console.warn('Poll failed, retrying...', e);
			}
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
		results = [];
		query = saved.query;
		dateFilter = saved.date_filter || '';
		maxPages = saved.max_pages;

		try {
			// 1. 저장된 검색 실행 요청
			const queueResponse = await apiRequest<{
				search_id: string;
				status: string;
				message: string;
			}>(`/saved/${saved.id}/run`, { method: 'POST' });

			// 2. 상태 폴링 (공통 함수 사용)
			const searchId = queueResponse.search_id;
			pendingSearchId = searchId;
			await pollForResults(searchId);
			await loadSavedSearches();
		} catch (e) {
			error = e instanceof Error ? e.message : '검색 실패';
		} finally {
			loading = false;
			pendingSearchId = null;
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

	// 스케줄 기능
	async function loadSchedules() {
		try {
			schedules = await apiRequest<Schedule[]>('/schedule/');
		} catch (e) {
			console.error('스케줄 로드 실패:', e);
		}
	}

	function getScheduleForSaved(savedId: number): Schedule | undefined {
		return schedules.find((s) => s.target_config.saved_search_id === savedId);
	}

	async function openScheduleModal(saved: SavedSearch, event: Event) {
		event.stopPropagation();
		selectedSavedSearch = saved;

		const existing = getScheduleForSaved(saved.id);
		if (existing) {
			editingSchedule = existing;
			const tw = existing.schedule_value.time_windows[0];
			scheduleTime = tw?.start || '09:00';
			scheduleEnabled = existing.enabled;
		} else {
			editingSchedule = null;
			scheduleTime = '09:00';
			scheduleEnabled = true;
		}

		showScheduleModal = true;
	}

	async function saveSchedule() {
		if (!selectedSavedSearch) return;

		try {
			if (editingSchedule) {
				// 수정
				await apiRequest(`/schedule/${editingSchedule.id}`, {
					method: 'PUT',
					body: JSON.stringify({
						schedule_value: {
							time_windows: [{ start: scheduleTime, end: scheduleTime }],
							daily_runs: 1,
							min_interval_hours: 1
						},
						enabled: scheduleEnabled
					})
				});
			} else {
				// 생성
				await apiRequest('/schedule/', {
					method: 'POST',
					body: JSON.stringify({
						saved_search_id: selectedSavedSearch.id,
						display_name: `${selectedSavedSearch.name} 자동 검색`,
						schedule_type: 'time_window',
						schedule_value: {
							time_windows: [{ start: scheduleTime, end: scheduleTime }],
							daily_runs: 1,
							min_interval_hours: 1
						},
						enabled: scheduleEnabled
					})
				});
			}

			showScheduleModal = false;
			await loadSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 저장 실패';
		}
	}

	async function deleteSchedule() {
		if (!editingSchedule) return;
		if (!confirm('스케줄을 삭제하시겠습니까?')) return;

		try {
			await apiRequest(`/schedule/${editingSchedule.id}`, { method: 'DELETE' });
			showScheduleModal = false;
			await loadSchedules();
		} catch (e) {
			error = '스케줄 삭제 실패';
		}
	}

	async function openRunsModal(scheduleId: number, event: Event) {
		event.stopPropagation();
		selectedScheduleId = scheduleId;

		try {
			const response = await apiRequest<{ items: ScheduleRun[] }>(
				`/schedule/${scheduleId}/runs?limit=10`
			);
			scheduleRuns = response.items;
			showRunsModal = true;
		} catch (e) {
			error = '실행 이력 조회 실패';
		}
	}

	function formatScheduleTime(schedule: Schedule): string {
		const tw = schedule.schedule_value.time_windows[0];
		return tw ? tw.start : '-';
	}

	onMount(() => {
		loadSavedSearches();
		loadHistory();
		loadSchedules();
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
				class="rounded-lg border border-border px-4 py-2 hover:bg-muted disabled:opacity-50"
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
				<div class="text-muted-foreground">검색 결과가 없습니다.</div>
			{:else}
				<div class="space-y-4">
					{#each results as result}
						<div class="rounded-lg bg-white p-4 shadow">
							<div class="flex items-start gap-3">
								<span class="w-6 font-mono text-sm text-muted-foreground">{result.rank}</span>
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
										<p class="mt-2 text-sm text-muted-foreground">{result.snippet}</p>
									{/if}
									{#if result.publish_date}
										<span class="mt-2 inline-block text-xs text-muted-foreground">
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
					class:text-muted-foreground={activeTab !== 'saved'}
				>
					저장된 검색
				</button>
				<button
					onclick={() => (activeTab = 'history')}
					class="flex-1 border-b-2 py-2 text-sm font-medium transition-colors"
					class:border-blue-500={activeTab === 'history'}
					class:text-blue-600={activeTab === 'history'}
					class:border-transparent={activeTab !== 'history'}
					class:text-muted-foreground={activeTab !== 'history'}
				>
					최근 검색
				</button>
			</div>

			<!-- 저장된 검색 목록 -->
			{#if activeTab === 'saved'}
				<div class="rounded-lg bg-white shadow">
					{#if savedSearches.length === 0}
						<div class="p-4 text-sm text-muted-foreground">저장된 검색이 없습니다.</div>
					{:else}
						<ul class="divide-y">
							{#each savedSearches as saved}
								<li class="hover:bg-muted">
									<div class="p-3">
										<div class="flex items-center justify-between">
											<button onclick={() => runSavedSearch(saved)} class="flex-1 text-left">
												<div class="flex items-center gap-2">
													{#if saved.is_favorite}
														<span class="text-yellow-500">★</span>
													{/if}
													<span class="text-sm font-medium">{saved.name}</span>
												</div>
												<div class="mt-1 text-xs text-muted-foreground">{saved.query}</div>
											</button>

											<!-- 액션 버튼 -->
											<div class="flex gap-1">
												<button
													onclick={(e) => toggleFavorite(saved, e)}
													class="p-1 text-muted-foreground hover:text-yellow-500"
													title="즐겨찾기"
												>
													{saved.is_favorite ? '★' : '☆'}
												</button>
												<button
													onclick={(e) => openScheduleModal(saved, e)}
													class="p-1 text-muted-foreground hover:text-green-500"
													title="스케줄 설정"
												>
													{#if getScheduleForSaved(saved.id)}
														<span class="text-green-500">⏰</span>
													{:else}
														⏰
													{/if}
												</button>
												{#if getScheduleForSaved(saved.id)}
													<button
														onclick={(e) => openRunsModal(getScheduleForSaved(saved.id)!.id, e)}
														class="p-1 text-xs text-muted-foreground hover:text-purple-500"
														title="실행 이력"
													>
														📊
													</button>
												{/if}
												{#if saved.last_search_id}
													<button
														onclick={(e) => loadLastResults(saved, e)}
														class="p-1 text-xs text-muted-foreground hover:text-blue-500"
														title="마지막 결과 보기"
													>
														📋
													</button>
												{/if}
												<button
													onclick={(e) => deleteSavedSearch(saved, e)}
													class="p-1 text-muted-foreground hover:text-red-500"
													title="삭제"
												>
													✕
												</button>
											</div>
										</div>

										<!-- 메타 정보 -->
										<div class="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
											{#if saved.date_filter}
												<span
													>{dateFilters.find((f) => f.value === saved.date_filter)?.label}</span
												>
											{/if}
											<span>{saved.max_pages}p</span>
											{#if getScheduleForSaved(saved.id)}
												{@const schedule = getScheduleForSaved(saved.id)!}
												<span class="text-green-600">
													⏰ {formatScheduleTime(schedule)}
													{schedule.enabled ? '' : '(중지)'}
												</span>
											{/if}
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
						<div class="p-4 text-sm text-muted-foreground">검색 기록이 없습니다.</div>
					{:else}
						<ul class="divide-y">
							{#each history as item}
								<li>
									<button
										onclick={() => loadFromHistory(item)}
										class="w-full p-3 text-left hover:bg-muted"
									>
										<div class="text-sm font-medium">{item.query}</div>
										<div class="mt-1 text-xs text-muted-foreground">
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

				<div class="text-sm text-muted-foreground">
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
					class="rounded-lg px-4 py-2 text-muted-foreground hover:bg-muted"
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

<!-- 스케줄 설정 모달 -->
{#if showScheduleModal && selectedSavedSearch}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
		<div class="w-96 rounded-lg bg-white p-6 shadow-xl">
			<h3 class="mb-4 text-lg font-semibold">
				{editingSchedule ? '스케줄 수정' : '스케줄 설정'}
			</h3>

			<div class="space-y-4">
				<div class="text-sm text-muted-foreground">
					<div><strong>검색명:</strong> {selectedSavedSearch.name}</div>
					<div><strong>검색어:</strong> {selectedSavedSearch.query}</div>
				</div>

				<div>
					<label for="schedule-time" class="mb-1 block text-sm font-medium">실행 시간</label>
					<input
						id="schedule-time"
						type="time"
						bind:value={scheduleTime}
						class="w-full rounded-lg border px-3 py-2"
					/>
				</div>

				<label class="flex items-center gap-2">
					<input type="checkbox" bind:checked={scheduleEnabled} />
					<span class="text-sm">스케줄 활성화</span>
				</label>

				{#if editingSchedule?.next_run_at}
					<div class="text-sm text-muted-foreground">
						다음 실행: {formatDate(editingSchedule.next_run_at)}
					</div>
				{/if}
			</div>

			<div class="mt-6 flex justify-between">
				{#if editingSchedule}
					<button onclick={deleteSchedule} class="rounded-lg px-4 py-2 text-red-600 hover:bg-red-50">
						삭제
					</button>
				{:else}
					<div></div>
				{/if}

				<div class="flex gap-2">
					<button
						onclick={() => (showScheduleModal = false)}
						class="rounded-lg px-4 py-2 text-muted-foreground hover:bg-muted"
					>
						취소
					</button>
					<button
						onclick={saveSchedule}
						class="rounded-lg bg-green-500 px-4 py-2 text-white hover:bg-green-600"
					>
						{editingSchedule ? '수정' : '저장'}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- 실행 이력 모달 -->
{#if showRunsModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
		<div class="max-h-[80vh] w-[500px] overflow-auto rounded-lg bg-white p-6 shadow-xl">
			<h3 class="mb-4 text-lg font-semibold">스케줄 실행 이력</h3>

			{#if scheduleRuns.length === 0}
				<div class="py-4 text-center text-muted-foreground">실행 이력이 없습니다.</div>
			{:else}
				<ul class="divide-y">
					{#each scheduleRuns as run}
						<li class="py-3">
							<div class="flex items-center justify-between">
								<div>
									<span class="text-sm">{formatDate(run.started_at)}</span>
									{#if run.status === 'completed'}
										<span class="ml-2 rounded bg-green-100 px-2 py-0.5 text-xs text-green-700">
											완료
										</span>
									{:else if run.status === 'failed'}
										<span class="ml-2 rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
											실패
										</span>
									{:else}
										<span class="ml-2 rounded bg-yellow-100 px-2 py-0.5 text-xs text-yellow-700">
											실행중
										</span>
									{/if}
								</div>
								<span class="text-sm text-muted-foreground">{run.collected_count}개 수집</span>
							</div>
							{#if run.error_message}
								<div class="mt-1 text-xs text-red-500">{run.error_message}</div>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}

			<div class="mt-4 flex justify-end">
				<button
					onclick={() => (showRunsModal = false)}
					class="rounded-lg px-4 py-2 text-muted-foreground hover:bg-muted"
				>
					닫기
				</button>
			</div>
		</div>
	</div>
{/if}
