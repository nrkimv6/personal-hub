<script lang="ts">
	import { onMount } from 'svelte';
	import { onDestroy } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import { search, pollSearchResult, getHistory, getSuggestions, getPresets, getStatus } from '$lib/api/fileSearch';
	import type {
		FileMatch,
		Preset,
		SearchHistoryItem,
		SearchMode,
		SearchRequest,
		SearchResponse,
		SearchSuggestionItem,
		StatusResponse
	} from '$lib/types/fileSearch';
	import { Search, Languages, XCircle, Loader2, Inbox, AlertTriangle, ChevronRight } from 'lucide-svelte';

	import SearchForm from './SearchForm.svelte';
	import SearchHistoryBar from './SearchHistoryBar.svelte';
	import PresetBar from './PresetBar.svelte';
	import ExtensionFilter from './ExtensionFilter.svelte';
	import IgnorePatterns from './IgnorePatterns.svelte';
	import PathInput from './PathInput.svelte';
	import ResultList from './ResultList.svelte';
	import EncodingFixer from '../utils/EncodingFixer.svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	type PageTab = 'search' | 'encoding';
	let pageTab: PageTab = $state('search');

	$effect(() => {
		const t = $page.url.searchParams.get('tab');
		pageTab = t === 'encoding' ? 'encoding' : 'search';
	});

	function setPageTab(tab: PageTab) {
		const url = new URL($page.url);
		if (tab === 'search') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, keepFocus: true });
	}

	// ────────────────────────────────────────────────────────────
	// 상태
	// ────────────────────────────────────────────────────────────
	let query = $state('');
	let mode: SearchMode = $state('both');
	let regex = $state(false);
	let caseSensitive = $state(false);
	let path = $state('');
	let extensions: string[] = $state([]);
	let excludes: string[] = $state([]);
	let ignorePatternExcludes: string[] = $state([]);
	let selectedPresetId: string | null = $state(null);

	let results: FileMatch[] = $state([]);
	let searchTimeMs = $state(0);
	let truncated = $state(false);
	let loading = $state(false);
	let error = $state('');
	let hasSearched = $state(false);

	let presets: Preset[] = $state([]);
	let status: StatusResponse | null = $state(null);

	let showFilters = $state(true);

	let historyItems: SearchHistoryItem[] = $state([]);
	let suggestionItems: SearchSuggestionItem[] = $state([]);
	let historyLoading = $state(false);
	let historyError = $state('');

	let snapshotSearchId: string | null = $state(null);

	// 검색 AbortController
	let abortController: AbortController | null = null;

	// 폴링 상태
	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let pollStatus = $state<string>(''); // pending / queued / processing / completed / failed

	const POLL_STATUS_LABELS: Record<string, string> = {
		pending: '큐 대기중',
		queued: '큐 대기중',
		processing: '검색 중...',
		completed: '완료',
		failed: '실패'
	};

	// ────────────────────────────────────────────────────────────
	// 초기화
	// ────────────────────────────────────────────────────────────
	async function refreshHistory() {
		historyLoading = true;
		historyError = '';
		try {
			const [h, s] = await Promise.all([getHistory(20), getSuggestions(10)]);
			historyItems = h;
			suggestionItems = s;
		} catch (e) {
			historyError = e instanceof Error ? e.message : '최근 검색/추천을 불러오지 못했습니다.';
		} finally {
			historyLoading = false;
		}
	}

	onMount(async () => {
		try {
			presets = await getPresets();
		} catch {}
		try {
			status = await getStatus();
		} catch {}
		await refreshHistory();
	});

	// ────────────────────────────────────────────────────────────
	// 전역 단축키 (Ctrl+Enter)
	// ────────────────────────────────────────────────────────────
	function handleGlobalKeydown(e: KeyboardEvent) {
		if (e.ctrlKey && e.key === 'Enter') {
			e.preventDefault();
			handleSearch();
		}
	}

	// ────────────────────────────────────────────────────────────
	// 프리셋 선택
	// ────────────────────────────────────────────────────────────
	function handlePresetSelect(preset: Preset | null) {
		if (!preset) {
			selectedPresetId = null;
			return;
		}
		selectedPresetId = preset.id;
		extensions = [...preset.extensions];
		excludes = [...preset.excludes];
		if (preset.paths.length > 0) path = preset.paths[0];
	}

	// ────────────────────────────────────────────────────────────
	// 폴링 정리
	// ────────────────────────────────────────────────────────────
	function clearPolling() {
		if (pollInterval !== null) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
	}

	onDestroy(() => {
		clearPolling();
		abortController?.abort();
	});

	// ────────────────────────────────────────────────────────────
	// 검색 실행
	// ────────────────────────────────────────────────────────────
	async function handleSearch() {
		if (!query.trim() || loading) return;
		snapshotSearchId = null;

		// 이전 요청 취소 및 폴링 정리
		abortController?.abort();
		clearPolling();
		abortController = new AbortController();

		loading = true;
		error = '';
		hasSearched = true;
		pollStatus = '';

		try {
			// 202 비동기 → search_id 수신
			const accepted = await search(
				{
					query: query.trim(),
					mode,
					regex,
					case_sensitive: caseSensitive,
					paths: path ? [path] : [],
					extensions,
					excludes: [...excludes, ...ignorePatternExcludes],
					preset: selectedPresetId ?? undefined,
					max_results: 100,
					context_lines: 2
				},
				abortController.signal
			);

			pollStatus = accepted.status;

			// 폴링 시작 (200ms 간격)
			await new Promise<void>((resolve, reject) => {
				pollInterval = setInterval(async () => {
					try {
						const poll = await pollSearchResult(accepted.search_id);
						pollStatus = poll.status;

						if (poll.status === 'completed') {
							clearPolling();
							if (poll.result) {
								results = poll.result.results;
								searchTimeMs = poll.result.search_time_ms;
								truncated = poll.result.truncated;
							} else {
								results = [];
							}
							resolve();
						} else if (poll.status === 'failed') {
							clearPolling();
							error = poll.error_message ?? '검색 중 오류가 발생했습니다.';
							results = [];
							resolve();
						}
					} catch (e) {
						clearPolling();
						reject(e);
					}
				}, 200);
			});

			// 최근 검색/추천 갱신 (실패해도 검색 결과는 유지)
			void refreshHistory();
		} catch (err: unknown) {
			clearPolling();
			if (err instanceof Error && err.name === 'AbortError') return; // 취소됨
			if (err instanceof Error && err.message.includes('타임아웃')) {
				error = '검색 시간이 초과되었습니다. RIPGREP_TIMEOUT 설정을 확인하세요.';
			} else if (err instanceof Error && err.message.includes('잘못된 정규식')) {
				error = `정규식 오류: ${err.message}`;
			} else {
				error = err instanceof Error ? err.message : '검색 중 오류가 발생했습니다.';
			}
			results = [];
		} finally {
			loading = false;
			pollStatus = '';
		}
	}

	function handleCancel() {
		abortController?.abort();
		clearPolling();
		loading = false;
		pollStatus = '';
	}

	function applySearchRequestToForm(req: SearchRequest) {
		query = req.query ?? '';
		mode = req.mode ?? 'both';
		regex = !!req.regex;
		caseSensitive = !!req.case_sensitive;
		path = Array.isArray(req.paths) && req.paths.length > 0 ? req.paths[0] : '';
		extensions = Array.isArray(req.extensions) ? [...req.extensions] : [];
		excludes = Array.isArray(req.excludes) ? [...req.excludes] : [];
		selectedPresetId = req.preset ?? null;
	}

	function handleSuggestionClick(q: string) {
		query = q;
		handleSearch();
	}

	async function handleHistoryClick(item: SearchHistoryItem) {
		// 진행 중 검색이 있으면 정리
		abortController?.abort();
		clearPolling();

		loading = true;
		error = '';
		hasSearched = true;
		pollStatus = '';
		snapshotSearchId = item.search_id;

		try {
			applySearchRequestToForm(item.request);
			const poll = await pollSearchResult(item.search_id);
			if (poll.status === 'completed') {
				if (poll.result) {
					results = poll.result.results;
					searchTimeMs = poll.result.search_time_ms;
					truncated = poll.result.truncated;
				} else {
					results = [];
				}
			} else if (poll.status === 'failed') {
				error = poll.error_message ?? '저장된 검색 결과를 불러오지 못했습니다.';
				results = [];
			} else {
				error = `저장된 검색이 아직 완료되지 않았습니다: ${poll.status}`;
				results = [];
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '저장된 검색 결과를 불러오지 못했습니다.';
			results = [];
		} finally {
			loading = false;
			pollStatus = '';
		}
	}
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

<div class="flex h-full flex-col gap-4 p-6">
	<!-- 탭 네비게이션 -->
	<div class="flex items-center gap-1 border-b border-border pb-2">
		<button
			onclick={() => setPageTab('search')}
			class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-t transition-colors {pageTab === 'search'
				? 'bg-primary/10 text-primary'
				: 'text-muted-foreground hover:text-foreground hover:bg-muted/40'}"
		>
			<Search size={16} /> 파일 검색
		</button>
		<button
			onclick={() => setPageTab('encoding')}
			class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-t transition-colors {pageTab === 'encoding'
				? 'bg-primary/10 text-primary'
				: 'text-muted-foreground hover:text-foreground hover:bg-muted/40'}"
		>
			<Languages size={16} /> 인코딩 변환
		</button>
	</div>

	{#if pageTab === 'encoding'}
		<EncodingFixer />
	{/if}

	{#if pageTab === 'search'}
	<!-- 페이지 제목 + 상태 뱃지 -->
	<PageHeader title="파일 검색" subtitle="로컬 파일을 빠르게 검색합니다">
		{#if status}
			<div class="flex items-center gap-2">
				<span
					class="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium
						   {status.everything_ok ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}"
					title={status.everything_message}
				>
					<span class="h-1.5 w-1.5 rounded-full {status.everything_ok ? 'bg-success' : 'bg-destructive'}"></span>
					Everything
				</span>
				<span
					class="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium
						   {status.ripgrep_ok ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}"
					title={status.ripgrep_path ?? '미설치'}
				>
					<span class="h-1.5 w-1.5 rounded-full {status.ripgrep_ok ? 'bg-success' : 'bg-destructive'}"></span>
					ripgrep
				</span>
			</div>
		{/if}
	</PageHeader>

	<!-- 도구 문제 경고 -->
	{#if status && (!status.everything_ok || !status.ripgrep_ok)}
		<div class="rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning flex items-start gap-2">
			<AlertTriangle size={18} class="shrink-0 mt-0.5" />
			<div>
				{#if !status.everything_ok}
					<p>Everything HTTP 서버에 연결할 수 없습니다 ({status.everything_message}). 파일명 검색이 불가합니다.</p>
				{/if}
				{#if !status.ripgrep_ok}
					<p>ripgrep이 설치되지 않았습니다. 내용 검색이 불가합니다. (<code>winget install BurntSushi.ripgrep.MSVC</code>)</p>
				{/if}
			</div>
		</div>
	{/if}

	<!-- 검색 에러 -->
	{#if error}
		<div class="flex items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
			<XCircle size={18} class="shrink-0" />
			<span class="flex-1">{error}</span>
			<button onclick={() => (error = '')} class="shrink-0 opacity-60 hover:opacity-100">×</button>
		</div>
	{/if}

	<!-- 검색 폼 -->
	<SearchForm
		bind:query
		bind:mode
		bind:regex
		bind:caseSensitive
		{loading}
		{snapshotSearchId}
		onsearch={handleSearch}
		oncancel={handleCancel}
	/>

	<SearchHistoryBar
		history={historyItems}
		suggestions={suggestionItems}
		loading={historyLoading}
		error={historyError}
		onsuggestion={handleSuggestionClick}
		onhistory={handleHistoryClick}
	/>

	{#if snapshotSearchId}
		<div class="rounded-lg border border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground flex items-center justify-between gap-3">
			<div class="min-w-0">
				<span class="font-medium text-foreground">저장 결과 보기</span>
				<span class="ml-2 truncate">search_id: <code class="text-[11px]">{snapshotSearchId}</code></span>
			</div>
			<div class="flex items-center gap-2 shrink-0">
				<button
					onclick={() => (snapshotSearchId = null)}
					class="rounded-md border border-border bg-background px-2.5 py-1 hover:bg-muted/40 transition-colors"
				>
					닫기
				</button>
				<button
					onclick={handleSearch}
					class="rounded-md bg-primary px-2.5 py-1 text-primary-foreground hover:opacity-90 transition-opacity"
				>
					다시 검색
				</button>
			</div>
		</div>
	{/if}

	<!-- 필터 영역 (접기/펼치기) -->
	<div class="rounded-lg border border-border bg-card">
		<button
			onclick={() => (showFilters = !showFilters)}
			class="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium
				   hover:bg-muted/50 transition-colors"
		>
			<span>필터 & 범위</span>
			<ChevronRight size={14} class="text-muted-foreground transition-transform {showFilters ? 'rotate-90' : ''}" />
		</button>

		{#if showFilters}
			<div class="border-t border-border px-4 py-3 space-y-3">
				<!-- 프리셋 -->
				<div class="space-y-1.5">
					<div class="text-xs font-medium text-muted-foreground">프리셋</div>
					<PresetBar
						{presets}
						{selectedPresetId}
						onselect={handlePresetSelect}
					/>
				</div>

				<!-- 경로 -->
				<div class="space-y-1.5">
					<div class="text-xs font-medium text-muted-foreground">검색 경로</div>
					<PathInput
						bind:path
						onchange={(p) => (path = p)}
					/>
				</div>

				<!-- 확장자 -->
				<div class="space-y-1.5">
					<div class="text-xs font-medium text-muted-foreground">확장자 필터</div>
					<ExtensionFilter
						bind:extensions
						onchange={(exts) => (extensions = exts)}
					/>
				</div>

				<!-- 무시 패턴 -->
				<div class="space-y-1.5">
					<IgnorePatterns onchange={(patterns) => (ignorePatternExcludes = patterns)} />
				</div>
			</div>
		{/if}
	</div>

	<!-- 결과 영역 -->
	<div class="flex-1 overflow-y-auto">
		{#if loading}
			<!-- 폴링 상태 표시 -->
			<div class="space-y-2">
				{#if pollStatus}
					<div class="flex items-center gap-2 text-sm text-muted-foreground px-2 py-1">
						<Loader2 size={16} class="animate-spin" />
						<span>{POLL_STATUS_LABELS[pollStatus] ?? pollStatus}</span>
					</div>
				{/if}
				{#each Array(4) as _}
					<div class="h-14 rounded-lg border border-border bg-card animate-skeleton-shimmer"></div>
				{/each}
			</div>
		{:else if !hasSearched}
			<!-- 초기 상태 -->
			<div class="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
				<Search size={48} class="mb-4 opacity-20" />
				<p class="text-sm">검색어를 입력하고 Enter를 눌러 검색하세요</p>
				<p class="text-xs mt-1 opacity-70">파일명 검색 (Everything) + 내용 검색 (ripgrep)</p>
			</div>
		{:else if results.length === 0}
			<!-- 빈 결과 -->
			<div class="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
				<Inbox size={48} class="mb-4 opacity-20" />
				<p class="text-sm font-medium">검색 결과가 없습니다</p>
				<p class="text-xs mt-1 opacity-70">검색어나 필터 조건을 변경해 보세요</p>
			</div>
		{:else}
			<ResultList {results} {query} {searchTimeMs} {truncated} />
		{/if}
	</div>
	{/if}
</div>
