<script lang="ts">
	import { onMount } from 'svelte';
	import { getFilePreview, openFile } from '$lib/api/fileSearch';
	import MarkdownContent from '$lib/components/markdown/MarkdownContent.svelte';
	import { toast } from '$lib/stores/toast';
	import type { FileMatch, ContentMatch, FilePreviewResponse } from '$lib/types/fileSearch';
	import MarkdownPreviewModal from './MarkdownPreviewModal.svelte';
	import { AlertTriangle, FileText, ClipboardList, ChevronRight, Copy } from 'lucide-svelte';

	interface Props {
		results: FileMatch[];
		query: string;
		searchTimeMs: number;
		truncated: boolean;
	}

	let { results, query, searchTimeMs, truncated }: Props = $props();

	let collapsed: Record<string, boolean> = $state({});
	let isMobileViewport = $state(false);

	let activePreviewPath: string | null = $state(null);
	let fullPreviewPath: string | null = $state(null);
	let previewCache: Record<string, FilePreviewResponse> = $state({});
	let previewLoadingPath: string | null = $state(null);
	let previewErrorByPath: Record<string, string> = $state({});
	let previewRawByPath: Record<string, boolean> = $state({});
	let fullPreview = $derived(fullPreviewPath ? previewCache[fullPreviewPath] ?? null : null);

	onMount(() => {
		const mediaQuery = window.matchMedia('(max-width: 639px)');
		const syncViewport = () => {
			isMobileViewport = mediaQuery.matches;
		};
		syncViewport();
		mediaQuery.addEventListener('change', syncViewport);
		return () => mediaQuery.removeEventListener('change', syncViewport);
	});

	$effect(() => {
		const alive = new Set(results.map((result) => result.file_path));
		const nextCollapsed = { ...collapsed };

		for (const file of results) {
			if (!(file.file_path in nextCollapsed)) {
				nextCollapsed[file.file_path] = file.matches.length > 0;
			}
		}

		for (const key of Object.keys(nextCollapsed)) {
			if (!alive.has(key)) {
				delete nextCollapsed[key];
			}
		}

		collapsed = nextCollapsed;

		if (activePreviewPath && !alive.has(activePreviewPath)) {
			activePreviewPath = null;
		}
		if (fullPreviewPath && !alive.has(fullPreviewPath)) {
			fullPreviewPath = null;
		}
		if (previewLoadingPath && !alive.has(previewLoadingPath)) {
			previewLoadingPath = null;
		}

		for (const key of Object.keys(previewCache)) {
			if (!alive.has(key)) delete previewCache[key];
		}
		for (const key of Object.keys(previewErrorByPath)) {
			if (!alive.has(key)) delete previewErrorByPath[key];
		}
		for (const key of Object.keys(previewRawByPath)) {
			if (!alive.has(key)) delete previewRawByPath[key];
		}
	});

	function toggleCollapse(filePath: string) {
		collapsed[filePath] = !collapsed[filePath];
	}

	async function handleOpenFile(filePath: string, lineNumber?: number) {
		try {
			await openFile(filePath, lineNumber);
		} catch (e) {
			console.error('파일 열기 실패:', e);
		}
	}

	async function loadPreview(filePath: string): Promise<void> {
		if (previewCache[filePath]) return;

		previewLoadingPath = filePath;
		delete previewErrorByPath[filePath];
		try {
			previewCache[filePath] = await getFilePreview(filePath);
		} catch (e) {
			previewErrorByPath[filePath] = humanizePreviewError(e);
		} finally {
			if (previewLoadingPath === filePath) {
				previewLoadingPath = null;
			}
		}
	}

	async function togglePreview(filePath: string): Promise<void> {
		if (activePreviewPath === filePath) {
			activePreviewPath = null;
			return;
		}
		activePreviewPath = filePath;
		await loadPreview(filePath);
	}

	async function openFullPreview(filePath: string): Promise<void> {
		activePreviewPath = filePath;
		await loadPreview(filePath);

		if (previewErrorByPath[filePath]) return;

		const preview = previewCache[filePath];
		if (!preview || preview.extension !== 'md') return;

		fullPreviewPath = filePath;
	}

	function closeFullPreview() {
		fullPreviewPath = null;
	}

	function toggleRawPreview(filePath: string) {
		previewRawByPath[filePath] = !previewRawByPath[filePath];
	}

	async function copyFilePath(filePath: string): Promise<void> {
		try {
			await navigator.clipboard.writeText(filePath);
			toast.success('경로 복사됨');
		} catch {
			toast.error('클립보드 복사 실패');
		}
	}

	function shortenPath(fullPath: string, maxLen = 60): string {
		if (fullPath.length <= maxLen) return fullPath;
		const sep = fullPath.includes('\\') ? '\\' : '/';
		const parts = fullPath.split(sep);
		const fileName = parts[parts.length - 1];
		const prefix = parts[0];
		return `${prefix}${sep}...${sep}${fileName}`;
	}

	function highlightLine(lineText: string, matches: ContentMatch['submatches']): string {
		if (!matches || matches.length === 0) {
			return escapeHtml(lineText);
		}
		const sorted = [...matches].sort((a, b) => a.start - b.start);
		let result = '';
		let cursor = 0;
		for (const sm of sorted) {
			if (sm.start > cursor) {
				result += escapeHtml(lineText.slice(cursor, sm.start));
			}
			result += `<mark class="bg-warning/30 text-foreground rounded px-0.5">${escapeHtml(lineText.slice(sm.start, sm.end))}</mark>`;
			cursor = sm.end;
		}
		if (cursor < lineText.length) {
			result += escapeHtml(lineText.slice(cursor));
		}
		return result;
	}

	function escapeHtml(text: string): string {
		return text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;');
	}

	function formatSize(bytes: number | null): string {
		if (bytes === null) return '';
		if (bytes < 1024) return `${bytes}B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
	}

	function humanizePreviewError(e: unknown): string {
		const raw = e instanceof Error ? e.message : String(e);

		if (raw.includes('미리보기 크기 제한') || raw.includes('256KB')) {
			return '파일이 256KB를 초과해 미리보기할 수 없습니다.';
		}
		if (raw.includes('지원하지 않는 확장자')) {
			return '지원하지 않는 확장자입니다. 텍스트 파일만 미리보기할 수 있습니다.';
		}
		if (raw.includes('binary')) {
			return '바이너리 파일은 미리보기할 수 없습니다.';
		}
		if (raw.includes('지원하지 않는 인코딩')) {
			return '지원하지 않는 인코딩입니다. (utf-8/cp949만 지원)';
		}
		if (raw.includes('파일을 찾을 수 없습니다') || raw.includes('디렉토리는 미리보기할 수 없습니다')) {
			return '파일을 찾을 수 없습니다.';
		}

		return raw;
	}

	function getFirstMatch(file: FileMatch) {
		return file.matches[0] ?? null;
	}
</script>

<div class="space-y-2">
	{#if results.length > 0}
		<div class="flex flex-wrap items-center gap-3 px-1 py-2 text-xs text-muted-foreground">
			<span>
				<strong class="text-foreground">{results.length}</strong>개 파일
				{#if results.some((result) => result.matches.length > 0)}
					· <strong class="text-foreground">{results.reduce((sum, result) => sum + result.matches.length, 0)}</strong>건 매칭
				{/if}
				· <span>{searchTimeMs}ms</span>
				{#if query}
					· <span class="text-foreground">"{query}"</span>
				{/if}
			</span>
			{#if truncated}
				<span class="flex items-center gap-1 rounded bg-warning/20 px-2 py-0.5 font-medium text-warning">
					<AlertTriangle size={14} />
					더 많은 결과가 있을 수 있습니다
				</span>
			{/if}
		</div>
	{/if}

	{#each results as file (file.file_path)}
		{@const firstMatch = getFirstMatch(file)}
		<div class="overflow-hidden rounded-xl border border-border bg-card">
			<button
				onclick={() => toggleCollapse(file.file_path)}
				class="flex w-full items-start gap-3 px-3 py-3 text-left transition-colors hover:bg-muted/50 group"
				aria-label={`${file.file_name} 결과 펼치기`}
			>
				<span class="mt-0.5 shrink-0 text-muted-foreground">
					{#if file.matches.length > 0}
						<FileText size={18} />
					{:else}
						<ClipboardList size={18} />
					{/if}
				</span>

				<div class="min-w-0 flex-1 space-y-1">
					<div class="flex flex-wrap items-center gap-2">
						<span
							class="cursor-pointer truncate text-sm font-semibold text-foreground transition-colors hover:text-primary"
							onclick={(event) => {
								event.stopPropagation();
								void togglePreview(file.file_path);
							}}
							title={file.file_path}
						>
							{file.file_name}
						</span>
						{#if file.matches.length > 0}
							<span class="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
								{file.matches.length}건
							</span>
						{/if}
						{#if file.match_source === 'both'}
							<span class="shrink-0 rounded-full bg-success/10 px-2 py-0.5 text-[11px] text-success">
								파일명+내용
							</span>
						{/if}
						{#if activePreviewPath === file.file_path}
							<span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-foreground">
								미리보기 열림
							</span>
						{/if}
					</div>

					<div class="truncate font-mono text-[11px] text-muted-foreground" title={file.file_path}>
						{shortenPath(file.file_path, isMobileViewport ? 42 : 68)}
					</div>

					{#if firstMatch}
						<div class="flex items-start gap-2 rounded-lg bg-muted/40 px-2.5 py-2 text-xs text-muted-foreground">
							<span class="shrink-0 font-mono text-primary/80">L{firstMatch.line_number}</span>
							<span class="line-clamp-1 min-w-0 flex-1">{firstMatch.line_text}</span>
							{#if file.matches.length > 1}
								<span class="shrink-0 text-[11px]">+{file.matches.length - 1}</span>
							{/if}
						</div>
					{/if}
				</div>

				<div class="flex shrink-0 items-start gap-2 text-xs text-muted-foreground">
					{#if file.file_size}
						<span class="hidden rounded-full bg-muted px-2 py-1 sm:inline-flex">{formatSize(file.file_size)}</span>
					{/if}
					<span
						class="rounded p-1 transition-colors hover:bg-muted/60"
						onclick={(event) => {
							event.stopPropagation();
							void copyFilePath(file.file_path);
						}}
						title="full path 복사"
					>
						<Copy size={16} />
					</span>
					<ChevronRight size={16} class="mt-1 transition-transform {collapsed[file.file_path] ? '' : 'rotate-90'}" />
				</div>
			</button>

			{#if !collapsed[file.file_path] && file.matches.length > 0}
				<div class="border-t border-border divide-y divide-border/50">
					{#each file.matches as match}
						{#each match.context_before as ctx}
							<div class="flex items-start gap-0 bg-muted/20 font-mono text-xs">
								<span class="w-12 shrink-0 select-none border-r border-border/40 px-2 py-1 text-right text-muted-foreground/50">
									·
								</span>
								<span class="whitespace-pre-wrap break-all px-3 py-1 text-muted-foreground/60">{ctx}</span>
							</div>
						{/each}

						<button
							class="flex w-full items-start gap-0 text-left transition-colors hover:bg-primary/5"
							onclick={() => handleOpenFile(file.file_path, match.line_number)}
						>
							<span class="w-12 shrink-0 select-none border-r border-primary/20 bg-primary/5 px-2 py-1 text-right font-mono text-xs text-primary/70">
								{match.line_number}
							</span>
							<span class="flex-1 whitespace-pre-wrap break-all px-3 py-1 font-mono text-xs">
								<!-- eslint-disable-next-line svelte/no-at-html-tags -->
								{@html highlightLine(match.line_text, match.submatches)}
							</span>
						</button>

						{#each match.context_after as ctx}
							<div class="flex items-start gap-0 bg-muted/20 font-mono text-xs">
								<span class="w-12 shrink-0 select-none border-r border-border/40 px-2 py-1 text-right text-muted-foreground/50">
									·
								</span>
								<span class="whitespace-pre-wrap break-all px-3 py-1 text-muted-foreground/60">{ctx}</span>
							</div>
						{/each}
					{/each}
				</div>
			{/if}

			{#if activePreviewPath === file.file_path}
				<div class="border-t border-border">
					{#if previewLoadingPath === file.file_path && !previewCache[file.file_path]}
						<div class="px-3 py-3 text-xs text-muted-foreground animate-pulse">미리보기 로드 중...</div>
					{:else if previewErrorByPath[file.file_path]}
						<div class="px-3 py-3 text-xs text-destructive">
							{previewErrorByPath[file.file_path]}
						</div>
					{:else if previewCache[file.file_path]}
						<div class="flex flex-wrap items-center gap-2 border-b border-border/60 px-3 py-2 text-xs text-muted-foreground">
							<span class="rounded bg-muted px-2 py-0.5 font-medium text-foreground">
								{previewCache[file.file_path].extension ? previewCache[file.file_path].extension.toUpperCase() : 'TEXT'}
							</span>
							<span class="font-mono">{previewCache[file.file_path].encoding}</span>
							<span class="font-mono">{formatSize(previewCache[file.file_path].size_bytes)}</span>
							{#if previewCache[file.file_path].extension === 'md'}
								<div class="ml-auto flex items-center gap-2">
									<button
										type="button"
										onclick={() => void openFullPreview(file.file_path)}
										class="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
									>
										전체보기
									</button>
									<button
										type="button"
										onclick={() => toggleRawPreview(file.file_path)}
										class="rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
									>
										{previewRawByPath[file.file_path] ? 'Markdown 보기' : 'Raw 보기'}
									</button>
								</div>
							{/if}
						</div>
						{#if previewCache[file.file_path].extension === 'md' && !previewRawByPath[file.file_path]}
							<MarkdownContent content={previewCache[file.file_path].content} variant="compact" class="max-h-[320px] overflow-auto px-3 py-2" />
						{:else}
							<pre class="max-h-[320px] overflow-auto whitespace-pre px-3 py-2 font-mono text-xs">{previewCache[file.file_path].content}</pre>
						{/if}
					{/if}
				</div>
			{/if}
		</div>
	{/each}
</div>

{#if fullPreviewPath && fullPreview}
	<MarkdownPreviewModal
		preview={fullPreview}
		raw={!!previewRawByPath[fullPreviewPath]}
		onClose={closeFullPreview}
		onToggleRaw={() => toggleRawPreview(fullPreview.file_path)}
		onOpenFile={() => void handleOpenFile(fullPreview.file_path)}
		onCopyPath={() => void copyFilePath(fullPreview.file_path)}
	/>
{/if}
