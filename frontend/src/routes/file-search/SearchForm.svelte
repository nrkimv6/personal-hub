<script lang="ts">
	import type { SearchMode } from '$lib/types/fileSearch';
	import { Search, Clock } from 'lucide-svelte';

	interface Props {
		query: string;
		mode: SearchMode;
		regex: boolean;
		caseSensitive: boolean;
		loading: boolean;
		onsearch: () => void;
		oncancel: () => void;
	}

	let {
		query = $bindable(''),
		mode = $bindable('both'),
		regex = $bindable(false),
		caseSensitive = $bindable(false),
		loading,
		onsearch,
		oncancel
	}: Props = $props();

	// 검색 히스토리 (localStorage)
	const HISTORY_KEY = 'file_search_history';
	const MAX_HISTORY = 10;

	let historyItems: string[] = $state([]);
	let showHistory = $state(false);
	let inputEl: HTMLInputElement | undefined = $state();

	function loadHistory() {
		try {
			const raw = localStorage.getItem(HISTORY_KEY);
			historyItems = raw ? JSON.parse(raw) : [];
		} catch {
			historyItems = [];
		}
	}

	function saveHistory(q: string) {
		if (!q.trim()) return;
		const filtered = historyItems.filter((h) => h !== q);
		const updated = [q, ...filtered].slice(0, MAX_HISTORY);
		historyItems = updated;
		try {
			localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
		} catch {}
	}

	function handleSubmit() {
		if (!query.trim() || loading) return;
		saveHistory(query.trim());
		showHistory = false;
		onsearch();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.ctrlKey || !e.shiftKey)) {
			e.preventDefault();
			handleSubmit();
		}
		if (e.key === 'Escape') {
			showHistory = false;
		}
	}

	function selectHistory(item: string) {
		query = item;
		showHistory = false;
		onsearch();
	}

	function onInputFocus() {
		loadHistory();
		if (historyItems.length > 0 && !query) showHistory = true;
	}

	function onInputClick() {
		if (historyItems.length > 0 && !query) showHistory = true;
	}

	// 외부 클릭 시 히스토리 닫기
	function handleDocClick(e: MouseEvent) {
		if (!(e.target as HTMLElement)?.closest?.('.search-form-container')) {
			showHistory = false;
		}
	}
</script>

<svelte:document onclick={handleDocClick} />

<div class="search-form-container space-y-3">
	<!-- 검색어 input -->
	<div class="relative">
		<div class="flex gap-2">
			<input
				bind:this={inputEl}
				bind:value={query}
				type="text"
				placeholder="파일명 또는 내용 검색... (Ctrl+Enter)"
				class="flex-1 rounded-lg border border-border bg-background px-4 py-2.5 text-sm
					   shadow-sm outline-none transition-colors
					   focus:border-primary focus:ring-2 focus:ring-primary/20
					   disabled:opacity-50"
				disabled={loading}
				onkeydown={handleKeydown}
				onfocus={onInputFocus}
				onclick={onInputClick}
			/>
			{#if loading}
				<button
					onclick={oncancel}
					class="rounded-lg border border-border bg-background px-3 py-2 text-sm
						   text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
				>
					취소
				</button>
			{:else}
				<button
					onclick={handleSubmit}
					disabled={!query.trim()}
					class="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground
						   shadow-sm transition-colors hover:bg-primary/90
						   disabled:cursor-not-allowed disabled:opacity-50"
				>
					<Search size={16} class="inline-block mr-1" /> 검색
				</button>
			{/if}
		</div>

		<!-- 히스토리 드롭다운 -->
		{#if showHistory && historyItems.length > 0}
			<div
				class="absolute top-full left-0 z-50 mt-1 w-full rounded-lg border border-border
					   bg-card shadow-md"
			>
				<div class="py-1 text-xs text-muted-foreground px-3 pt-2">최근 검색</div>
				{#each historyItems as item}
					<button
						onclick={() => selectHistory(item)}
						class="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors truncate"
					>
						<Clock size={14} class="inline-block mr-1 text-muted-foreground/70" /> {item}
					</button>
				{/each}
			</div>
		{/if}
	</div>

	<!-- 모드 + 옵션 -->
	<div class="flex flex-wrap items-center gap-4">
		<!-- 검색 모드 -->
		<div class="flex items-center gap-1 rounded-lg border border-border bg-background p-1">
			{#each [['filename', '파일명'], ['content', '내용'], ['both', '둘 다']] as [val, label]}
				<button
					onclick={() => (mode = val as SearchMode)}
					class="rounded-md px-3 py-1 text-xs font-medium transition-colors
						   {mode === val
						? 'bg-primary text-primary-foreground shadow-sm'
						: 'text-muted-foreground hover:bg-muted hover:text-foreground'}"
				>
					{label}
				</button>
			{/each}
		</div>

		<!-- 정규식 토글 -->
		<label class="flex cursor-pointer items-center gap-1.5 text-sm">
			<input
				type="checkbox"
				bind:checked={regex}
				class="h-4 w-4 rounded accent-primary"
			/>
			<span class="font-mono text-xs text-muted-foreground">.*</span>
			<span>정규식</span>
		</label>

		<!-- 대소문자 토글 -->
		<label class="flex cursor-pointer items-center gap-1.5 text-sm">
			<input
				type="checkbox"
				bind:checked={caseSensitive}
				class="h-4 w-4 rounded accent-primary"
			/>
			<span class="font-mono text-xs text-muted-foreground">Aa</span>
			<span>대소문자 구분</span>
		</label>

		<!-- 로딩 표시 -->
		{#if loading}
			<span class="flex items-center gap-1.5 text-sm text-muted-foreground animate-pulse">
				<span class="inline-block h-2 w-2 rounded-full bg-primary animate-pulse"></span>
				검색 중...
			</span>
		{/if}
	</div>
</div>
