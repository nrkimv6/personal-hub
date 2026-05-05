<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import {
		search,
		pollSearchResult,
		getFrequentCombos,
		getHistory,
		getPresets,
		getStatus
	} from '$lib/api/fileSearch';
	import type {
		ExtensionSuggestionItem,
		ExtensionSuggestionSection,
		FileMatch,
		FrequentSearchComboItem,
		Preset,
		SearchHistoryItem,
		SearchMode,
		SearchRequest,
		StatusResponse
	} from '$lib/types/fileSearch';
	import { Search, Languages, XCircle, Loader2, Inbox, AlertTriangle, ChevronRight, FileText } from 'lucide-svelte';

	import SearchForm from './SearchForm.svelte';
	import SearchHistoryBar from './SearchHistoryBar.svelte';
	import SearchHelperOverlay from './SearchHelperOverlay.svelte';
	import type { SearchHelperTab } from './SearchHelperOverlay.svelte';
	import PresetBar from './PresetBar.svelte';
	import ExtensionFilter from './ExtensionFilter.svelte';
	import IgnorePatterns from './IgnorePatterns.svelte';
	import PathInput from './PathInput.svelte';
	import ResultList from './ResultList.svelte';
	import EncodingFixer from '../utils/EncodingFixer.svelte';
	import Mp4GifTab from './Mp4GifTab.svelte';
	import ImagePdfTab from './ImagePdfTab.svelte';

	type PageTab = 'search' | 'encoding' | 'mp4-gif' | 'image-pdf';
	type SearchRecord = {
		request: SearchRequest;
		weight: number;
	};

	let pageTab: PageTab = $state('search');
	const pageTabs = [
		{ id: 'search', label: '파일 검색', icon: Search },
		{ id: 'encoding', label: '인코딩 변환', icon: Languages },
		{ id: 'mp4-gif', label: 'MP4 → GIF' },
		{ id: 'image-pdf', label: '이미지 → PDF', icon: FileText }
	];

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
	let showHelperOverlay = $state(false);
	let helperTab: SearchHelperTab = $state('combos');
	let isMobileViewport = $state(false);

	let historyItems: SearchHistoryItem[] = $state([]);
	let frequentComboItems: FrequentSearchComboItem[] = $state([]);
	let historyLoading = $state(false);
	let comboLoading = $state(false);
	let historyError = $state('');
	let comboError = $state('');

	let snapshotSearchId: string | null = $state(null);
	let abortController: AbortController | null = null;
	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let pollStatus = $state<string>('');

	const POLL_STATUS_LABELS: Record<string, string> = {
		pending: '큐 대기중',
		queued: '큐 대기중',
		processing: '검색 중...',
		completed: '완료',
		failed: '실패'
	};

	const selectedPreset = $derived(
		selectedPresetId ? presets.find((preset) => preset.id === selectedPresetId) ?? null : null
	);

	const totalExcludeCount = $derived(excludes.length + ignorePatternExcludes.length);

	const filterSummaryItems = $derived.by(() => {
		const items: string[] = [];

		if (selectedPreset) {
			items.push(`프리셋 ${selectedPreset.name}`);
		}
		if (path.trim()) {
			items.push(shortPath(path.trim(), 30));
		}
		if (extensions.length > 0) {
			const [first, ...rest] = extensions;
			items.push(rest.length > 0 ? `.${first} +${rest.length}` : `.${first}`);
		}
		if (totalExcludeCount > 0) {
			items.push(`제외 ${totalExcludeCount}`);
		}

		return items;
	});

	const helperSummary = $derived.by(() => {
		const items: string[] = [];
		if (frequentComboItems.length > 0) {
			items.push(`조합 ${frequentComboItems.length}`);
		}
		if (historyItems.length > 0) {
			items.push(`최근 ${historyItems.length}`);
		}
		return items;
	});
	const pageSubtitle = $derived.by(() => {
		if (pageTab === 'encoding') {
			return '텍스트 파일의 인코딩 문제를 점검하고 변환합니다.';
		}
		if (pageTab === 'mp4-gif') {
			return 'MP4 파일을 업로드하고 GIF로 변환합니다.';
		}
		if (pageTab === 'image-pdf') {
			return '여러 이미지 파일을 하나의 PDF로 병합합니다.';
		}
		return '로컬 파일 검색, 인코딩 변환, MP4 → GIF 작업을 한곳에서 처리합니다.';
	});
	const hasStatusIssue = $derived.by(() => {
		const currentStatus = status;
		return currentStatus ? !currentStatus.everything_ok || !currentStatus.ripgrep_ok : false;
	});

	const searchRecords = $derived.by(() => {
		const records: SearchRecord[] = [];

		for (const item of historyItems) {
			records.push({
				request: item.request,
				weight: 1
			});
		}

		for (const item of frequentComboItems) {
			records.push({
				request: item.request,
				weight: Math.max(item.count, 1)
			});
		}

		return records;
	});

	const extensionSuggestionGroups = $derived.by(() => {
		const selected = new Set(extensions.map(normalizeExtension));
		const used = new Set<string>();
		const sections: ExtensionSuggestionSection[] = [];

		const recentItems = collectExtensionItems(
			historyItems.flatMap((item) => item.request.extensions ?? []),
			selected,
			used,
			4
		);
		if (recentItems.length > 0) {
			sections.push({
				id: 'recent',
				label: '최근 사용',
				items: recentItems
			});
		}

		const contextualRecords = searchRecords.filter((record) => matchesCurrentContext(record.request));
		const contextualItems = collectExtensionItemsFromRecords(contextualRecords, selected, used, 5);
		if (contextualItems.length > 0) {
			sections.push({
				id: 'context',
				label: query.trim() ? '현재 검색과 함께 자주 사용' : '현재 모드/경로와 자주 사용',
				items: contextualItems
			});
		}

		const presetAndPathRecords = searchRecords.filter((record) => {
			if (selectedPresetId && record.request.preset === selectedPresetId) return true;
			if (!path.trim()) return false;
			return record.request.paths?.some((itemPath) => pathMatches(path, itemPath)) ?? false;
		});
		const presetItems = collectExtensionItemsFromRecords(presetAndPathRecords, selected, used, 5);
		if (presetItems.length > 0) {
			sections.push({
				id: 'preset',
				label: selectedPreset ? `${selectedPreset.name} 추천` : '경로 기반 추천',
				items: presetItems
			});
		}

		return sections;
	});

	async function refreshHistory() {
		historyLoading = true;
		comboLoading = true;
		historyError = '';
		comboError = '';
		try {
			const [historyResult, comboResult] = await Promise.allSettled([
				getHistory(20),
				getFrequentCombos(10)
			]);
			if (historyResult.status === 'fulfilled') {
				historyItems = historyResult.value;
			} else {
				historyItems = [];
				historyError =
					historyResult.reason instanceof Error
						? historyResult.reason.message
						: '최근 검색을 불러오지 못했습니다.';
			}
			if (comboResult.status === 'fulfilled') {
				frequentComboItems = comboResult.value;
			} else {
				frequentComboItems = [];
				comboError =
					comboResult.reason instanceof Error
						? comboResult.reason.message
						: '자주 쓰는 조합을 불러오지 못했습니다.';
			}
		} finally {
			historyLoading = false;
			comboLoading = false;
		}
	}

	onMount(() => {
		const mediaQuery = window.matchMedia('(max-width: 639px)');
		const syncViewport = () => {
			isMobileViewport = mediaQuery.matches;
			if (mediaQuery.matches) {
				showFilters = false;
			}
		};
		syncViewport();
		mediaQuery.addEventListener('change', syncViewport);

		void (async () => {
			try {
				presets = await getPresets();
			} catch {}
			try {
				status = await getStatus();
			} catch {}
			await refreshHistory();
		})();

		return () => mediaQuery.removeEventListener('change', syncViewport);
	});

	function handleGlobalKeydown(event: KeyboardEvent) {
		if (event.ctrlKey && event.key === 'Enter') {
			event.preventDefault();
			handleSearch();
		}
	}

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

	async function handleSearch() {
		if (!query.trim() || loading) return;
		snapshotSearchId = null;
		showHelperOverlay = false;

		abortController?.abort();
		clearPolling();
		abortController = new AbortController();

		loading = true;
		error = '';
		hasSearched = true;
		pollStatus = '';

		try {
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
					} catch (pollError) {
						clearPolling();
						reject(pollError);
					}
				}, 200);
			});

			void refreshHistory();
		} catch (err: unknown) {
			clearPolling();
			if (err instanceof Error && err.name === 'AbortError') return;
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

	function applySearchRequestToForm(request: SearchRequest) {
		query = request.query ?? '';
		mode = request.mode ?? 'both';
		regex = !!request.regex;
		caseSensitive = !!request.case_sensitive;
		path = Array.isArray(request.paths) && request.paths.length > 0 ? request.paths[0] : '';
		extensions = Array.isArray(request.extensions)
			? [...new Set(request.extensions.map(normalizeExtension))]
			: [];
		excludes = Array.isArray(request.excludes) ? [...request.excludes] : [];
		selectedPresetId = request.preset ?? null;
	}

	async function handleHistoryClick(item: SearchHistoryItem) {
		abortController?.abort();
		clearPolling();
		showHelperOverlay = false;

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
		} catch (historyErrorValue) {
			error =
				historyErrorValue instanceof Error
					? historyErrorValue.message
					: '저장된 검색 결과를 불러오지 못했습니다.';
			results = [];
		} finally {
			loading = false;
			pollStatus = '';
		}
	}

	function handleFrequentComboClick(item: FrequentSearchComboItem) {
		abortController?.abort();
		clearPolling();
		snapshotSearchId = null;
		showHelperOverlay = false;
		applySearchRequestToForm(item.request);
		void handleSearch();
	}

	function openHelper(tab: SearchHelperTab) {
		helperTab = tab;
		showHelperOverlay = true;
	}

	function closeHelper() {
		showHelperOverlay = false;
	}

	function normalizeExtension(ext: string): string {
		return ext.trim().replace(/^\./, '').toLowerCase();
	}

	function shortPath(value: string, maxLen = 32): string {
		if (value.length <= maxLen) return value;
		const normalized = value.replace(/\\/g, '/');
		const parts = normalized.split('/').filter(Boolean);
		if (parts.length <= 2) return value;
		return `${parts[0]}/.../${parts[parts.length - 1]}`;
	}

	function pathMatches(currentPath: string, candidatePath: string): boolean {
		const current = currentPath.trim().replace(/\\/g, '/').toLowerCase();
		const candidate = candidatePath.trim().replace(/\\/g, '/').toLowerCase();
		return current.length > 0 && candidate.length > 0 && (candidate.includes(current) || current.includes(candidate));
	}

	function matchesCurrentContext(request: SearchRequest): boolean {
		const normalizedQuery = query.trim().toLowerCase();
		const requestQuery = request.query?.trim().toLowerCase() ?? '';
		const hasQueryMatch =
			normalizedQuery.length > 0 &&
			requestQuery.length > 0 &&
			(requestQuery.includes(normalizedQuery) || normalizedQuery.includes(requestQuery));
		const hasModeMatch = request.mode === mode;
		const hasPresetMatch = selectedPresetId ? request.preset === selectedPresetId : false;
		const hasPathMatch =
			path.trim().length > 0 &&
			(request.paths?.some((itemPath) => pathMatches(path, itemPath)) ?? false);
		return hasQueryMatch || hasPresetMatch || hasPathMatch || hasModeMatch;
	}

	function collectExtensionItems(
		source: string[],
		selected: Set<string>,
		used: Set<string>,
		limit: number
	): ExtensionSuggestionItem[] {
		const items: ExtensionSuggestionItem[] = [];
		for (const ext of source) {
			const normalized = normalizeExtension(ext);
			if (!normalized || selected.has(normalized) || used.has(normalized)) continue;
			used.add(normalized);
			items.push({ ext: normalized });
			if (items.length >= limit) break;
		}
		return items;
	}

	function collectExtensionItemsFromRecords(
		records: SearchRecord[],
		selected: Set<string>,
		used: Set<string>,
		limit: number
	): ExtensionSuggestionItem[] {
		const counts = new Map<string, number>();

		for (const record of records) {
			const recordExtensions = [...new Set((record.request.extensions ?? []).map(normalizeExtension))];
			for (const ext of recordExtensions) {
				if (!ext || selected.has(ext) || used.has(ext)) continue;
				counts.set(ext, (counts.get(ext) ?? 0) + record.weight);
			}
		}

		return [...counts.entries()]
			.sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
			.slice(0, limit)
			.map(([ext, count]) => {
				used.add(ext);
				return { ext, count };
			});
	}
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

{#snippet headerActions()}
	{#if pageTab === 'search' && status}
		<div class="flex flex-wrap items-center gap-2">
			<span
				class="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium {status.everything_ok ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}"
				title={status.everything_message}
			>
				<span class="h-1.5 w-1.5 rounded-full {status.everything_ok ? 'bg-success' : 'bg-destructive'}"></span>
				Everything
			</span>
			<span
				class="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium {status.ripgrep_ok ? 'bg-success/10 text-success' : 'bg-destructive/10 text-destructive'}"
				title={status.ripgrep_path ?? '미설치'}
			>
				<span class="h-1.5 w-1.5 rounded-full {status.ripgrep_ok ? 'bg-success' : 'bg-destructive'}"></span>
				ripgrep
			</span>
		</div>
	{/if}
{/snippet}

{#snippet searchToolbar()}
	{#if pageTab === 'search' && hasStatusIssue}
		<div class="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">
			<AlertTriangle size={18} class="mt-0.5 shrink-0" />
			<div>
				{#if status && !status.everything_ok}
					<p>Everything HTTP 서버에 연결할 수 없습니다 ({status.everything_message}). 파일명 검색이 불가합니다.</p>
				{/if}
				{#if status && !status.ripgrep_ok}
					<p>ripgrep이 설치되지 않았습니다. 내용 검색이 불가합니다. (<code>winget install BurntSushi.ripgrep.MSVC</code>)</p>
				{/if}
			</div>
		</div>
	{/if}
{/snippet}

<TabbedPageLayout
	title="파일 도구"
	subtitle={pageSubtitle}
	actions={pageTab === 'search' ? headerActions : undefined}
	primaryTabs={pageTabs}
	bind:activePrimaryTab={pageTab}
	primaryQueryParam="tab"
	primaryReplaceState={false}
	toolbar={pageTab === 'search' ? searchToolbar : undefined}
	density="compact"
	containerClass="flex h-full min-h-0 flex-col gap-3 p-4 lg:p-6"
	contentClass="min-h-0 flex-1"
>
	{#if pageTab === 'encoding'}
		<EncodingFixer />
	{:else if pageTab === 'mp4-gif'}
		<Mp4GifTab />
	{:else if pageTab === 'image-pdf'}
		<ImagePdfTab />
	{:else}
		<div class="flex h-full min-h-0 flex-col gap-4">
			<div class="space-y-4">
				{#if error}
					<div class="flex items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
						<XCircle size={18} class="shrink-0" />
						<span class="flex-1">{error}</span>
						<button onclick={() => (error = '')} class="shrink-0 opacity-60 hover:opacity-100">×</button>
					</div>
				{/if}

				<SearchForm
					bind:query
					bind:mode
					bind:regex
					bind:caseSensitive
					{loading}
					{snapshotSearchId}
					helperOverlayOpen={showHelperOverlay}
					onsearch={handleSearch}
					oncancel={handleCancel}
				/>

				<SearchHistoryBar
					history={historyItems}
					frequentCombos={frequentComboItems}
					{historyLoading}
					{comboLoading}
					{historyError}
					{comboError}
					onopen={openHelper}
					oncombo={handleFrequentComboClick}
					onhistory={handleHistoryClick}
				/>

				{#if snapshotSearchId}
					<div class="flex flex-col gap-3 rounded-2xl border border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
						<div class="min-w-0">
							<span class="font-medium text-foreground">저장 결과 보기</span>
							<span class="ml-2 truncate">search_id: <code class="text-[11px]">{snapshotSearchId}</code></span>
						</div>
						<div class="flex items-center gap-2 shrink-0">
							<button
								onclick={() => (snapshotSearchId = null)}
								class="rounded-md border border-border bg-background px-2.5 py-1 transition-colors hover:bg-muted/40"
							>
								닫기
							</button>
							<button
								onclick={handleSearch}
								class="rounded-md bg-primary px-2.5 py-1 text-primary-foreground transition-opacity hover:opacity-90"
							>
								다시 검색
							</button>
						</div>
					</div>
				{/if}

				<div class="rounded-2xl border border-border bg-card">
					<button
						onclick={() => (showFilters = !showFilters)}
						class="flex w-full items-center justify-between gap-4 px-4 py-3 text-left text-sm font-medium transition-colors hover:bg-muted/50"
						aria-label="필터 및 범위 토글"
					>
						<div class="min-w-0 flex-1">
							<div class="text-sm font-medium text-foreground">필터 & 범위</div>
							<div class="mt-1 flex flex-wrap gap-1.5">
								{#if filterSummaryItems.length > 0}
									{#each filterSummaryItems.slice(0, isMobileViewport ? 2 : 4) as item (`filter-${item}`)}
										<span class="rounded-full border border-border bg-background px-2 py-0.5 text-[11px] font-normal text-muted-foreground">
											{item}
										</span>
									{/each}
								{:else}
									<span class="text-xs font-normal text-muted-foreground">전체 범위 · 확장자 제한 없음</span>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-2 shrink-0">
							{#if helperSummary.length > 0}
								<span class="hidden text-[11px] text-muted-foreground sm:inline">
									{helperSummary.join(' · ')}
								</span>
							{/if}
							<ChevronRight size={14} class="text-muted-foreground transition-transform {showFilters ? 'rotate-90' : ''}" />
						</div>
					</button>

					{#if showFilters}
						<div class="space-y-4 border-t border-border px-4 py-4">
							<div class="space-y-1.5">
								<div class="text-xs font-medium text-muted-foreground">프리셋</div>
								<PresetBar {presets} {selectedPresetId} onselect={handlePresetSelect} />
							</div>

							<div class="space-y-1.5">
								<div class="text-xs font-medium text-muted-foreground">검색 경로</div>
								<PathInput bind:path onchange={(nextPath) => (path = nextPath)} />
							</div>

							<div class="space-y-1.5">
								<div class="text-xs font-medium text-muted-foreground">확장자 필터</div>
								<ExtensionFilter
									bind:extensions
									suggestionGroups={extensionSuggestionGroups}
									onchange={(nextExtensions) => (extensions = nextExtensions)}
								/>
							</div>

							<div class="space-y-1.5">
								<IgnorePatterns onchange={(patterns) => (ignorePatternExcludes = patterns)} />
							</div>
						</div>
					{/if}
				</div>
			</div>

			<div class="min-h-64 flex-1 overflow-y-auto sm:min-h-72">
			{#if loading && results.length === 0}
				<div class="space-y-2">
					{#if pollStatus}
						<div class="flex items-center gap-2 px-2 py-1 text-sm text-muted-foreground">
							<Loader2 size={16} class="animate-spin" />
							<span>{POLL_STATUS_LABELS[pollStatus] ?? pollStatus}</span>
						</div>
					{/if}
					{#each Array(4) as _, index}
						<div class="h-14 rounded-lg border border-border bg-card animate-skeleton-shimmer" data-skeleton={index}></div>
					{/each}
				</div>
			{:else if !hasSearched}
				<div class="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
					<Search size={48} class="mb-4 opacity-20" />
					<p class="text-sm">검색어를 입력하고 Enter를 눌러 검색하세요</p>
					<p class="mt-1 text-xs opacity-70">파일명 검색 (Everything) + 내용 검색 (ripgrep)</p>
				</div>
			{:else if results.length === 0}
				<div class="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
					<Inbox size={48} class="mb-4 opacity-20" />
					<p class="text-sm font-medium">검색 결과가 없습니다</p>
					<p class="mt-1 text-xs opacity-70">검색어나 필터 조건을 변경해 보세요</p>
				</div>
			{:else}
				<div class="space-y-3">
					{#if loading}
						<div class="sticky top-0 z-10 flex justify-center">
							<div class="flex items-center gap-2 rounded-full border border-border bg-background/95 px-3 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur">
								<Loader2 size={14} class="animate-spin" />
								<span>{POLL_STATUS_LABELS[pollStatus] ?? '검색 중...'}</span>
							</div>
						</div>
					{/if}

					<ResultList {results} {query} {searchTimeMs} {truncated} />
				</div>
			{/if}
			</div>

			<SearchHelperOverlay
				open={showHelperOverlay}
				activeTab={helperTab}
			history={historyItems}
			frequentCombos={frequentComboItems}
			{historyLoading}
			{comboLoading}
			{historyError}
			{comboError}
			onclose={closeHelper}
			ontabchange={(tab) => (helperTab = tab)}
			oncombo={handleFrequentComboClick}
				onhistory={handleHistoryClick}
			/>
		</div>
	{/if}
</TabbedPageLayout>
