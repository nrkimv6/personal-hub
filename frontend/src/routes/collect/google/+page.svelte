<script lang="ts">
	import { onMount } from 'svelte';
	import type { Component } from 'svelte';
	import GoogleResultsTab from './GoogleResultsTab.svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import {
		Search,
		ClipboardList,
		Star,
		Pencil,
		Clock,
		BarChart3,
		X,
		ChevronUp,
		ChevronDown
	} from 'lucide-svelte';

	// 최상위 탭: 검색 실행 / 검색결과 관리
	type MainTab = 'search' | 'results';
	let mainTab: MainTab = $state('search');

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
		search_params?: { lr?: string; cr?: string; as_sitesearch?: string; num?: number; exclude_keywords?: string[] } | null;
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

	interface ScheduleRecentResult {
		schedule_id: number;
		schedule_name?: string;
		saved_search_name?: string;
		query?: string;
		enabled: boolean;
		last_search?: {
			search_id: string;
			query: string;
			date_filter?: string;
			status: string;
			total_results: number;
			created_at: string;
			completed_at?: string;
			results: SearchResult[];
		};
		last_run_at?: string;
	}

	interface ScheduleSearchHistory {
		search_id: string;
		query: string;
		date_filter?: string;
		status: string;
		total_results: number;
		created_at: string;
		completed_at?: string;
		results: SearchResult[];
	}

	// API 함수
	const API_BASE = '/api/v1/google';

	async function apiRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
		const response = await fetchWithTimeout(`${API_BASE}${endpoint}`, {
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
	let editingSavedSearch: SavedSearch | null = $state(null);
	let subTab: 'saved' | 'history' | 'schedule-results' = $state('saved');

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

	// 스케줄 결과 상태
	let scheduleRecentResults: ScheduleRecentResult[] = $state([]);
	let expandedScheduleId: number | null = $state(null);
	let scheduleSearchHistories: ScheduleSearchHistory[] = $state([]);
	let loadingScheduleResults = $state(false);

	const dateFilters = [
		{ value: '', label: '전체 기간' },
		{ value: '1h', label: '최근 1시간' },
		{ value: '24h', label: '최근 24시간' },
		{ value: '1w', label: '최근 1주일' },
		{ value: '1m', label: '최근 1개월' },
		{ value: '1y', label: '최근 1년' }
	];

	// 고급 옵션 상태
	let showAdvancedOptions = $state(false);
	let searchLang = $state('');
	let searchCountry = $state('');
	let searchSite = $state('');
	let searchNum = $state(10);
	let excludeKeywords = $state('');

	const languageOptions = [
		{ value: '', label: '전체' },
		{ value: 'lang_ko', label: '한국어' },
		{ value: 'lang_en', label: '영어' },
		{ value: 'lang_ja', label: '일본어' }
	];

	const countryOptions = [
		{ value: '', label: '전체' },
		{ value: 'countryKR', label: '한국' },
		{ value: 'countryUS', label: '미국' },
		{ value: 'countryJP', label: '일본' }
	];

	// 현재 폴링 중인 검색 ID
	let pendingSearchId: string | null = $state(null);

	// search_params 헬퍼: 현재 고급 옵션 값을 객체로 구성
	function buildSearchParams(): Record<string, string | number | string[]> | undefined {
		const params: Record<string, string | number | string[]> = {};
		if (searchLang) params.lr = searchLang;
		if (searchCountry) params.cr = searchCountry;
		if (searchSite) params.as_sitesearch = searchSite;
		if (searchNum !== 10) params.num = searchNum;
		if (excludeKeywords.trim()) {
			params.exclude_keywords = excludeKeywords.split(',').map(k => k.trim()).filter(Boolean);
		}
		return Object.keys(params).length > 0 ? params : undefined;
	}

	// 탭 정의
	const googleMainTabs: { id: string; label: string; icon: string | Component }[] = [
		{ id: 'search', label: '검색 실행', icon: Search as unknown as Component },
		{ id: 'results', label: '검색결과 관리', icon: ClipboardList as unknown as Component }
	];
	const googleSubTabs = [
		{ id: 'saved', label: '저장된 검색' },
		{ id: 'history', label: '최근 검색' },
		{ id: 'schedule-results', label: '스케줄 결과' }
	];

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
					max_pages: maxPages,
					search_params: buildSearchParams()
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
		if (!saveName.trim()) return;

		try {
			if (editingSavedSearch) {
				// 수정 모드: PUT
				await apiRequest(`/saved/${editingSavedSearch.id}`, {
					method: 'PUT',
					body: JSON.stringify({
						name: saveName.trim(),
						query: query.trim(),
						date_filter: dateFilter || undefined,
						max_pages: maxPages,
						is_favorite: saveAsFavorite,
						search_params: buildSearchParams()
					})
				});
			} else {
				// 생성 모드: POST
				if (!query.trim()) return;
				await apiRequest('/saved', {
					method: 'POST',
					body: JSON.stringify({
						name: saveName.trim(),
						query: query.trim(),
						date_filter: dateFilter || undefined,
						max_pages: maxPages,
						is_favorite: saveAsFavorite,
						search_params: buildSearchParams()
					})
				});
			}
			showSaveModal = false;
			saveName = '';
			saveAsFavorite = false;
			editingSavedSearch = null;
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

	// 수정 모달 열기
	function openEditModal(saved: SavedSearch, event: Event) {
		event.stopPropagation();
		editingSavedSearch = saved;
		saveName = saved.name;
		query = saved.query;
		dateFilter = saved.date_filter || '';
		maxPages = saved.max_pages;
		saveAsFavorite = saved.is_favorite;
		// search_params 복원
		if (saved.search_params) {
			searchLang = saved.search_params.lr || '';
			searchCountry = saved.search_params.cr || '';
			searchSite = saved.search_params.as_sitesearch || '';
			searchNum = saved.search_params.num || 10;
			excludeKeywords = (saved.search_params.exclude_keywords || []).join(', ');
			showAdvancedOptions = true;
		} else {
			searchLang = '';
			searchCountry = '';
			searchSite = '';
			searchNum = 10;
			excludeKeywords = '';
			showAdvancedOptions = false;
		}
		showSaveModal = true;
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

	// 스케줄 결과 기능
	async function loadScheduleRecentResults() {
		try {
			scheduleRecentResults = await apiRequest<ScheduleRecentResult[]>('/schedule/recent-results');
		} catch (e) {
			console.error('스케줄 결과 로드 실패:', e);
		}
	}

	async function loadScheduleSearchResults(scheduleId: number) {
		if (expandedScheduleId === scheduleId) {
			expandedScheduleId = null;
			scheduleSearchHistories = [];
			return;
		}

		loadingScheduleResults = true;
		expandedScheduleId = scheduleId;

		try {
			const response = await apiRequest<{
				items: ScheduleSearchHistory[];
				total: number;
			}>(`/schedule/${scheduleId}/search-results?limit=10`);
			scheduleSearchHistories = response.items;
		} catch (e) {
			console.error('스케줄 검색 결과 로드 실패:', e);
			scheduleSearchHistories = [];
		} finally {
			loadingScheduleResults = false;
		}
	}

	function loadScheduleResultToMain(searchHistory: ScheduleSearchHistory) {
		results = searchHistory.results;
		query = searchHistory.query;
		dateFilter = searchHistory.date_filter || '';
	}


	$effect(() => {
		if (mainTab === 'search' && subTab === 'schedule-results') {
			loadScheduleRecentResults();
		}
	});

	onMount(() => {
		const urlParams = new URLSearchParams(window.location.search);
		const tabParam = urlParams.get('tab');
		if (tabParam === 'results') {
			mainTab = 'results';
		} else {
			mainTab = 'search';
			if (tabParam === 'saved' || tabParam === 'history' || tabParam === 'schedule-results') {
				subTab = tabParam;
			} else {
				const urlSubTab = urlParams.get('subtab');
				subTab =
					urlSubTab === 'saved' || urlSubTab === 'history' || urlSubTab === 'schedule-results'
						? urlSubTab
						: 'saved';
			}
		}

		loadSavedSearches();
		loadHistory();
		loadSchedules();
	});
</script>

<svelte:head>
	<title>구글 검색 | Monitor Page</title>
	<style>
		body {
			overscroll-behavior-y: contain;
		}
	</style>
</svelte:head>

<div class="p-4 lg:p-6 space-y-4">
	<PageHeader title="구글 검색" />

	<TabNav tabs={googleMainTabs} bind:activeTab={mainTab} variant="secondary" queryParam="tab" />

	{#if mainTab === 'results'}
		<GoogleResultsTab />
	{:else}

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
				class="rounded-lg bg-primary px-6 py-2 text-white hover:bg-primary-hover disabled:opacity-50 flex items-center gap-2"
			>
				{#if loading}
					<span class="animate-spin"><Clock size={18} /></span> 검색 중...
				{:else}
					<Search size={18} /> 검색
				{/if}
			</button>

			<button
				onclick={() => {
					editingSavedSearch = null;
					showSaveModal = true;
				}}
				disabled={!query.trim()}
				class="rounded-lg border border-border px-4 py-2 hover:bg-muted disabled:opacity-50"
				title="검색 조건 저장"
			>
				저장
			</button>
		</div>

		<!-- 고급 옵션 토글 -->
		<button
			onclick={() => (showAdvancedOptions = !showAdvancedOptions)}
			class="mt-3 text-sm text-muted-foreground hover:text-foreground flex items-center gap-1"
		>
			{#if showAdvancedOptions}
				<ChevronDown size={14} />
			{:else}
				<ChevronUp size={14} />
			{/if} 고급 옵션
		</button>

		<!-- 고급 옵션 패널 -->
		{#if showAdvancedOptions}
			<div class="mt-3 flex flex-wrap gap-4">
				<div>
					<label class="mb-1 block text-xs text-muted-foreground">언어</label>
					<select bind:value={searchLang} class="rounded-lg border px-3 py-1.5 text-sm">
						{#each languageOptions as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
				</div>
				<div>
					<label class="mb-1 block text-xs text-muted-foreground">국가</label>
					<select bind:value={searchCountry} class="rounded-lg border px-3 py-1.5 text-sm">
						{#each countryOptions as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
				</div>
				<div>
					<label class="mb-1 block text-xs text-muted-foreground">사이트 제한</label>
					<input
						type="text"
						bind:value={searchSite}
						placeholder="예: booking.naver.com"
						class="rounded-lg border px-3 py-1.5 text-sm"
					/>
				</div>
				<div>
					<label class="mb-1 block text-xs text-muted-foreground">페이지당 결과</label>
					<select bind:value={searchNum} class="rounded-lg border px-3 py-1.5 text-sm">
						{#each [10, 20, 50] as n}
							<option value={n}>{n}개</option>
						{/each}
					</select>
				</div>
				<div class="w-full">
					<label for="exclude-keywords" class="mb-1 block text-xs text-muted-foreground">제외 키워드</label>
					<input
						id="exclude-keywords"
						type="text"
						bind:value={excludeKeywords}
						placeholder="콤마로 구분 (예: 구매, 판매, 광고)"
						class="w-full rounded-lg border px-3 py-1.5 text-sm"
					/>
				</div>
			</div>
		{/if}
	</div>

	{#if error}
		<div class="mb-6 rounded-lg bg-error-light p-4 text-error">{error}</div>
	{/if}

	<div class="grid grid-cols-1 gap-6 lg:grid-cols-4">
		<!-- 사이드바: 저장된 검색 + 히스토리 (모바일에서 먼저 표시) -->
		<div class="order-1 max-h-72 overflow-y-auto lg:order-2 lg:max-h-none lg:overflow-y-visible">
			<div class="mb-4">
				<TabNav tabs={googleSubTabs} bind:activeTab={subTab} variant="secondary" size="compact" queryParam="subtab" />
			</div>

			<!-- 저장된 검색 목록 -->
			{#if subTab === 'saved'}
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
														<Star size={14} class="fill-warning text-warning" />
													{/if}
													<span class="text-sm font-medium">{saved.name}</span>
												</div>
												<div class="mt-1 text-xs text-muted-foreground">{saved.query}</div>
											</button>

											<!-- 액션 버튼 -->
											<div class="flex gap-1">
												<button
													onclick={(e) => toggleFavorite(saved, e)}
													class="p-1 text-muted-foreground hover:text-warning"
													title="즐겨찾기"
												>
													<Star size={16} class={saved.is_favorite ? 'fill-warning text-warning' : ''} />
												</button>
												<button
													onclick={(e) => openEditModal(saved, e)}
													class="p-1 text-muted-foreground hover:text-primary"
													title="수정"
												>
													<Pencil size={16} />
												</button>
												<button
													onclick={(e) => openScheduleModal(saved, e)}
													class="p-1 text-muted-foreground hover:text-success"
													title="스케줄 설정"
												>
													<Clock size={16} class={getScheduleForSaved(saved.id) ? 'text-success' : ''} />
												</button>
												{#if getScheduleForSaved(saved.id)}
													<button
														onclick={(e) => openRunsModal(getScheduleForSaved(saved.id)!.id, e)}
														class="p-1 text-xs text-muted-foreground hover:text-purple-500"
														title="실행 이력"
													>
														<BarChart3 size={16} />
													</button>
												{/if}
												{#if saved.last_search_id}
													<button
														onclick={(e) => loadLastResults(saved, e)}
														class="p-1 text-xs text-muted-foreground hover:text-primary"
														title="마지막 결과 보기"
													>
														<ClipboardList size={16} />
													</button>
												{/if}
												<button
													onclick={(e) => deleteSavedSearch(saved, e)}
													class="p-1 text-muted-foreground hover:text-error"
													title="삭제"
												>
													<X size={16} />
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
												<span class="text-success flex items-center gap-1">
													<Clock size={12} /> {formatScheduleTime(schedule)}
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
			{#if subTab === 'history'}
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

			<!-- 스케줄 결과 -->
			{#if subTab === 'schedule-results'}
				<div class="rounded-lg bg-white shadow">
					{#if scheduleRecentResults.length === 0}
						<div class="p-4 text-sm text-muted-foreground">스케줄이 없습니다.</div>
					{:else}
						<ul class="divide-y">
							{#each scheduleRecentResults as item}
								<li>
									<!-- 스케줄 헤더 -->
									<button
										onclick={() => loadScheduleSearchResults(item.schedule_id)}
										class="w-full p-3 text-left hover:bg-muted"
									>
										<div class="flex items-center justify-between">
											<div class="flex items-center gap-2">
												<span
													class="inline-block h-2 w-2 rounded-full"
													class:bg-success={item.enabled}
													class:bg-muted-foreground={!item.enabled}
												></span>
												<span class="text-sm font-medium">
													{item.saved_search_name || item.schedule_name}
												</span>
											</div>
											<span class="text-xs text-muted-foreground">
												{#if expandedScheduleId === item.schedule_id}
													<ChevronUp size={14} />
												{:else}
													<ChevronDown size={14} />
												{/if}
											</span>
										</div>
										<div class="mt-1 text-xs text-muted-foreground">{item.query}</div>
										{#if item.last_search}
											<div class="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
												<span>{item.last_search.total_results}개 결과</span>
												<span>· {formatDate(item.last_search.completed_at || item.last_search.created_at)}</span>
											</div>
										{:else if item.last_run_at}
											<div class="mt-1 text-xs text-muted-foreground">
												마지막 실행: {formatDate(item.last_run_at)}
											</div>
										{:else}
											<div class="mt-1 text-xs text-muted-foreground">실행 기록 없음</div>
										{/if}
									</button>

									<!-- 최근 결과 미리보기: 마지막 검색 결과 바로 표시 -->
									{#if item.last_search && expandedScheduleId !== item.schedule_id}
										<div class="border-t px-3 pb-2">
											<button
												onclick={() => loadScheduleResultToMain(item.last_search!)}
												class="mt-1 text-xs text-primary hover:underline"
											>
												최근 결과 보기 ({item.last_search.total_results}개)
											</button>
										</div>
									{/if}

									<!-- 확장: 검색 히스토리 목록 -->
									{#if expandedScheduleId === item.schedule_id}
										<div class="border-t bg-gray-50">
											{#if loadingScheduleResults}
												<div class="p-3 text-center text-xs text-muted-foreground">
													로딩 중...
												</div>
											{:else if scheduleSearchHistories.length === 0}
												<div class="p-3 text-center text-xs text-muted-foreground">
													검색 결과가 없습니다.
												</div>
											{:else}
												<ul class="divide-y divide-gray-200">
													{#each scheduleSearchHistories as sh}
														<li>
															<button
																onclick={() => loadScheduleResultToMain(sh)}
																class="w-full p-3 text-left hover:bg-gray-100"
															>
																<div class="flex items-center justify-between">
																	<span class="text-xs font-medium">
																		{formatDate(sh.completed_at || sh.created_at)}
																	</span>
																	<span class="text-xs text-muted-foreground">
																		{sh.total_results}개
																	</span>
																</div>
																{#if sh.date_filter}
																	<span class="text-xs text-muted-foreground">
																		{dateFilters.find((f) => f.value === sh.date_filter)?.label}
																	</span>
																{/if}
															</button>
														</li>
													{/each}
												</ul>
											{/if}
										</div>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/if}
		</div>

		<!-- 검색 결과 (모바일에서 아래 표시) -->
		<div class="order-2 lg:order-1 lg:col-span-3">
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
										class="font-medium text-primary hover:underline"
									>
										{result.title}
									</a>
									{#if result.display_url}
										<div class="mt-1 text-sm text-success">{result.display_url}</div>
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
	</div>

{/if} <!-- mainTab === 'search' -->
</div>

<!-- 저장/수정 모달 -->
{#if showSaveModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
		<div class="w-96 rounded-lg bg-white p-6 shadow-xl">
			<h3 class="mb-4 text-lg font-semibold">
				{editingSavedSearch ? '검색 조건 수정' : '검색 조건 저장'}
			</h3>

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

				{#if editingSavedSearch}
					<!-- 수정 모드: 편집 가능한 필드 -->
					<div>
						<label for="edit-query" class="mb-1 block text-sm font-medium">검색어</label>
						<input
							id="edit-query"
							type="text"
							bind:value={query}
							class="w-full rounded-lg border px-3 py-2"
						/>
					</div>
					<div class="flex gap-4">
						<div class="flex-1">
							<label for="edit-date-filter" class="mb-1 block text-sm font-medium">날짜 필터</label>
							<select id="edit-date-filter" bind:value={dateFilter} class="w-full rounded-lg border px-3 py-2">
								{#each dateFilters as filter}
									<option value={filter.value}>{filter.label}</option>
								{/each}
							</select>
						</div>
						<div>
							<label for="edit-max-pages" class="mb-1 block text-sm font-medium">페이지 수</label>
							<select id="edit-max-pages" bind:value={maxPages} class="rounded-lg border px-3 py-2">
								{#each [1, 2, 3, 5, 10] as pages}
									<option value={pages}>{pages}</option>
								{/each}
							</select>
						</div>
					</div>

					<!-- 수정 모드: 고급 옵션 -->
					<button
						onclick={() => (showAdvancedOptions = !showAdvancedOptions)}
						class="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1"
					>
						{#if showAdvancedOptions}
							<ChevronDown size={14} />
						{:else}
							<ChevronUp size={14} />
						{/if} 고급 옵션
					</button>
					{#if showAdvancedOptions}
						<div class="flex flex-wrap gap-3">
							<div class="flex-1">
								<label class="mb-1 block text-xs text-muted-foreground">언어</label>
								<select bind:value={searchLang} class="w-full rounded-lg border px-2 py-1.5 text-sm">
									{#each languageOptions as opt}
										<option value={opt.value}>{opt.label}</option>
									{/each}
								</select>
							</div>
							<div class="flex-1">
								<label class="mb-1 block text-xs text-muted-foreground">국가</label>
								<select bind:value={searchCountry} class="w-full rounded-lg border px-2 py-1.5 text-sm">
									{#each countryOptions as opt}
										<option value={opt.value}>{opt.label}</option>
									{/each}
								</select>
							</div>
							<div class="w-full">
								<label class="mb-1 block text-xs text-muted-foreground">사이트 제한</label>
								<input
									type="text"
									bind:value={searchSite}
									placeholder="예: booking.naver.com"
									class="w-full rounded-lg border px-2 py-1.5 text-sm"
								/>
							</div>
							<div>
								<label class="mb-1 block text-xs text-muted-foreground">페이지당 결과</label>
								<select bind:value={searchNum} class="rounded-lg border px-2 py-1.5 text-sm">
									{#each [10, 20, 50] as n}
										<option value={n}>{n}개</option>
									{/each}
								</select>
							</div>
							<div class="w-full">
								<label for="exclude-keywords-2" class="mb-1 block text-xs text-muted-foreground">제외 키워드</label>
								<input
									id="exclude-keywords-2"
									type="text"
									bind:value={excludeKeywords}
									placeholder="콤마로 구분 (예: 구매, 판매, 광고)"
									class="w-full rounded-lg border px-2 py-1.5 text-sm"
								/>
							</div>
						</div>
					{/if}
				{:else}
					<!-- 생성 모드: 현재 검색 폼 값 표시 (읽기 전용) -->
					<div class="text-sm text-muted-foreground">
						<div><strong>검색어:</strong> {query}</div>
						<div>
							<strong>날짜 필터:</strong>
							{dateFilters.find((f) => f.value === dateFilter)?.label || '전체'}
						</div>
						<div><strong>페이지 수:</strong> {maxPages}</div>
					</div>
				{/if}

				<label class="flex items-center gap-2">
					<input type="checkbox" bind:checked={saveAsFavorite} />
					<span class="text-sm">즐겨찾기에 추가</span>
				</label>
			</div>

			<div class="mt-6 flex justify-end gap-2">
				<button
					onclick={() => {
						showSaveModal = false;
						editingSavedSearch = null;
					}}
					class="rounded-lg px-4 py-2 text-muted-foreground hover:bg-muted"
				>
					취소
				</button>
				<button
					onclick={saveCurrentSearch}
					disabled={!saveName.trim()}
					class="rounded-lg bg-primary px-4 py-2 text-white hover:bg-primary-hover disabled:opacity-50"
				>
					{editingSavedSearch ? '수정' : '저장'}
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
					<button onclick={deleteSchedule} class="rounded-lg px-4 py-2 text-error hover:bg-error-light">
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
						class="rounded-lg bg-success px-4 py-2 text-white hover:bg-success/90"
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
										<span class="ml-2 rounded bg-success-light px-2 py-0.5 text-xs text-success">
											완료
										</span>
									{:else if run.status === 'failed'}
										<span class="ml-2 rounded bg-error-light px-2 py-0.5 text-xs text-error">
											실패
										</span>
									{:else}
										<span class="ml-2 rounded bg-warning-light px-2 py-0.5 text-xs text-warning-foreground">
											실행중
										</span>
									{/if}
								</div>
								<span class="text-sm text-muted-foreground">{run.collected_count}개 수집</span>
							</div>
							{#if run.error_message}
								<div class="mt-1 text-xs text-error">{run.error_message}</div>
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
