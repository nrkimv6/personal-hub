<script lang="ts">
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

	// 파일별 접기/펼치기 상태
	let collapsed: Record<string, boolean> = $state({});

	let activePreviewPath: string | null = $state(null);
	let fullPreviewPath: string | null = $state(null);
	let previewCache: Record<string, FilePreviewResponse> = $state({});
	let previewLoadingPath: string | null = $state(null);
	let previewErrorByPath: Record<string, string> = $state({});
	let previewRawByPath: Record<string, boolean> = $state({});
	let fullPreview = $derived(fullPreviewPath ? previewCache[fullPreviewPath] ?? null : null);

	$effect(() => {
		const alive = new Set(results.map((r) => r.file_path));

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

	/** 경로를 앞부분 축약해 표시 (최대 60자) */
	function shortenPath(fullPath: string, maxLen = 60): string {
		if (fullPath.length <= maxLen) return fullPath;
		const sep = fullPath.includes('\\') ? '\\' : '/';
		const parts = fullPath.split(sep);
		const fileName = parts[parts.length - 1];
		const prefix = parts[0]; // 드라이브 또는 루트
		return `${prefix}${sep}...${sep}${fileName}`;
	}

	/** 매칭 키워드를 amber 하이라이트로 렌더링할 HTML 생성 */
	function highlightLine(lineText: string, matches: ContentMatch['submatches']): string {
		if (!matches || matches.length === 0) {
			return escapeHtml(lineText);
		}
		// submatches를 start 기준으로 정렬
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
</script>

<div class="space-y-1">
	<!-- 결과 요약 -->
	{#if results.length > 0}
		<div class="flex items-center gap-3 px-1 py-2 text-xs text-muted-foreground">
			<span>
				<strong class="text-foreground">{results.length}</strong>개 파일
				{#if results.some((r) => r.matches.length > 0)}
					· <strong class="text-foreground">{results.reduce((s, r) => s + r.matches.length, 0)}</strong>건 매칭
				{/if}
				· <span>{searchTimeMs}ms</span>
			</span>
			{#if truncated}
				<span class="rounded bg-warning/20 px-2 py-0.5 text-warning font-medium flex items-center gap-1">
					<AlertTriangle size={14} /> 더 많은 결과가 있을 수 있습니다
				</span>
			{/if}
		</div>
	{/if}

	<!-- 결과 목록 -->
	{#each results as file (file.file_path)}
		<div class="rounded-lg border border-border bg-card overflow-hidden">
			<!-- 파일 헤더 -->
			<button
				onclick={() => toggleCollapse(file.file_path)}
				class="flex w-full items-center gap-2 px-3 py-2.5 text-left
					   hover:bg-muted/50 transition-colors group"
			>
				<!-- 아이콘 + 파일명 -->
				<span class="shrink-0 text-muted-foreground">
					{#if file.matches.length > 0}
						<FileText size={18} />
					{:else}
						<ClipboardList size={18} />
					{/if}
				</span>
				<div class="flex-1 min-w-0">
					<div class="flex items-center gap-2 flex-wrap">
						<span
							class="font-medium text-sm truncate cursor-pointer
								   hover:text-primary transition-colors"
							onclick={(e) => { e.stopPropagation(); void togglePreview(file.file_path); }}
							title={file.file_path}
						>
							{file.file_name}
						</span>
						{#if file.matches.length > 0}
							<span class="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary font-medium">
								{file.matches.length}건
							</span>
						{/if}
						{#if file.match_source === 'both'}
							<span class="shrink-0 rounded-full bg-success/10 px-2 py-0.5 text-xs text-success">파일명+내용</span>
						{/if}
					</div>
					<div class="font-mono text-xs text-muted-foreground truncate mt-0.5" title={file.file_path}>
						{shortenPath(file.file_path)}
					</div>
				</div>

				<!-- 메타 + 화살표 -->
				<div class="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
					<span
						class="rounded p-1 hover:bg-muted/60 transition-colors cursor-pointer"
						onclick={(e) => { e.stopPropagation(); void copyFilePath(file.file_path); }}
						title="full path 복사"
					>
						<Copy size={16} />
					</span>
					{#if file.file_size}
						<span>{formatSize(file.file_size)}</span>
					{/if}
					<ChevronRight size={16} class="transition-transform {collapsed[file.file_path] ? '' : 'rotate-90'}" />
				</div>
			</button>

			<!-- 매칭 라인 목록 (접기/펼치기) -->
			{#if !collapsed[file.file_path] && file.matches.length > 0}
				<div class="border-t border-border divide-y divide-border/50">
					{#each file.matches as match}
						<!-- 컨텍스트 전 -->
						{#each match.context_before as ctx}
							<div class="flex items-start gap-0 bg-muted/20 font-mono text-xs">
								<span class="w-12 shrink-0 select-none py-1 px-2 text-right text-muted-foreground/50 border-r border-border/40">
									·
								</span>
								<span class="py-1 px-3 text-muted-foreground/60 whitespace-pre-wrap break-all">{ctx}</span>
							</div>
						{/each}

						<!-- 매칭 라인 -->
						<button
							class="flex w-full items-start gap-0 hover:bg-primary/5 transition-colors cursor-pointer text-left"
							onclick={() => handleOpenFile(file.file_path, match.line_number)}
						>
							<span
								class="w-12 shrink-0 select-none py-1 px-2 text-right font-mono text-xs
									   text-primary/70 border-r border-primary/20 bg-primary/5"
							>
								{match.line_number}
							</span>
							<span
								class="flex-1 py-1 px-3 font-mono text-xs whitespace-pre-wrap break-all"
							>
								<!-- eslint-disable-next-line svelte/no-at-html-tags -->
								{@html highlightLine(match.line_text, match.submatches)}
							</span>
						</button>

						<!-- 컨텍스트 후 -->
						{#each match.context_after as ctx}
							<div class="flex items-start gap-0 bg-muted/20 font-mono text-xs">
								<span class="w-12 shrink-0 select-none py-1 px-2 text-right text-muted-foreground/50 border-r border-border/40">
									·
								</span>
								<span class="py-1 px-3 text-muted-foreground/60 whitespace-pre-wrap break-all">{ctx}</span>
							</div>
						{/each}
					{/each}
				</div>
			{/if}

			<!-- 텍스트 미리보기 -->
			{#if activePreviewPath === file.file_path}
				<div class="border-t border-border">
					{#if previewLoadingPath === file.file_path && !previewCache[file.file_path]}
						<div class="px-3 py-3 text-xs text-muted-foreground animate-pulse">미리보기 로드 중...</div>
					{:else if previewErrorByPath[file.file_path]}
						<div class="px-3 py-3 text-xs text-destructive">
							{previewErrorByPath[file.file_path]}
						</div>
					{:else if previewCache[file.file_path]}
						<div class="flex flex-wrap items-center gap-2 px-3 py-2 text-xs text-muted-foreground border-b border-border/60">
							<span class="rounded bg-muted px-2 py-0.5 text-foreground font-medium">
								{previewCache[file.file_path].extension ? previewCache[file.file_path].extension.toUpperCase() : 'TEXT'}
							</span>
							<span class="font-mono">{previewCache[file.file_path].encoding}</span>
							<span class="font-mono">{formatSize(previewCache[file.file_path].size_bytes)}</span>
							{#if previewCache[file.file_path].extension === 'md'}
								<div class="ml-auto flex items-center gap-2">
									<button
										type="button"
										onclick={() => void openFullPreview(file.file_path)}
										class="rounded-md border border-border bg-background px-2 py-1 text-[11px]
											   text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
									>
										전체보기
									</button>
									<button
										type="button"
										onclick={() => toggleRawPreview(file.file_path)}
										class="rounded-md border border-border bg-background px-2 py-1 text-[11px]
											   text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
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
