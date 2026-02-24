<script lang="ts">
	import { onMount } from 'svelte';
	import { onDestroy } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import { search, pollSearchResult, getPresets, getStatus } from '$lib/api/fileSearch';
	import type {
		FileMatch,
		Preset,
		SearchMode,
		SearchResponse,
		StatusResponse
	} from '$lib/types/fileSearch';

	import SearchForm from './SearchForm.svelte';
	import PresetBar from './PresetBar.svelte';
	import ExtensionFilter from './ExtensionFilter.svelte';
	import PathInput from './PathInput.svelte';
	import ResultList from './ResultList.svelte';

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
	onMount(async () => {
		try {
			presets = await getPresets();
		} catch {}
		try {
			status = await getStatus();
		} catch {}
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
					excludes,
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
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

<div class="flex h-full flex-col gap-4 p-6">
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
		<div class="rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">
			{#if !status.everything_ok}
				⚠️ Everything HTTP 서버에 연결할 수 없습니다 ({status.everything_message}). 파일명 검색이 불가합니다.
			{/if}
			{#if !status.ripgrep_ok}
				⚠️ ripgrep이 설치되지 않았습니다. 내용 검색이 불가합니다. (<code>winget install BurntSushi.ripgrep.MSVC</code>)
			{/if}
		</div>
	{/if}

	<!-- 검색 에러 -->
	{#if error}
		<div class="flex items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
			<span class="shrink-0">❌</span>
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
		onsearch={handleSearch}
		oncancel={handleCancel}
	/>

	<!-- 필터 영역 (접기/펼치기) -->
	<div class="rounded-lg border border-border bg-card">
		<button
			onclick={() => (showFilters = !showFilters)}
			class="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium
				   hover:bg-muted/50 transition-colors"
		>
			<span>필터 & 범위</span>
			<span class="text-muted-foreground text-xs transition-transform {showFilters ? 'rotate-90' : ''}">▶</span>
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
						<span class="animate-spin text-base">⏳</span>
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
				<div class="text-5xl mb-4">🔎</div>
				<p class="text-sm">검색어를 입력하고 Enter를 눌러 검색하세요</p>
				<p class="text-xs mt-1 opacity-70">파일명 검색 (Everything) + 내용 검색 (ripgrep)</p>
			</div>
		{:else if results.length === 0}
			<!-- 빈 결과 -->
			<div class="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
				<div class="text-5xl mb-4">📭</div>
				<p class="text-sm font-medium">검색 결과가 없습니다</p>
				<p class="text-xs mt-1 opacity-70">검색어나 필터 조건을 변경해 보세요</p>
			</div>
		{:else}
			<ResultList {results} {query} {searchTimeMs} {truncated} />
		{/if}
	</div>
</div>
