<script lang="ts">
	import { openFile } from '$lib/api/fileSearch';
	import type { FileMatch, ContentMatch } from '$lib/types/fileSearch';

	interface Props {
		results: FileMatch[];
		query: string;
		searchTimeMs: number;
		truncated: boolean;
	}

	let { results, query, searchTimeMs, truncated }: Props = $props();

	// 파일별 접기/펼치기 상태
	let collapsed: Record<string, boolean> = $state({});

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
				<span class="rounded bg-warning/20 px-2 py-0.5 text-warning font-medium">
					⚠️ 더 많은 결과가 있을 수 있습니다
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
				<span class="text-base shrink-0">
					{file.matches.length > 0 ? '📄' : '📋'}
				</span>
				<div class="flex-1 min-w-0">
					<div class="flex items-center gap-2 flex-wrap">
						<span
							class="font-medium text-sm truncate cursor-pointer
								   hover:text-primary transition-colors"
							onclick={(e) => { e.stopPropagation(); handleOpenFile(file.file_path); }}
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
					{#if file.file_size}
						<span>{formatSize(file.file_size)}</span>
					{/if}
					<span class="transition-transform {collapsed[file.file_path] ? '' : 'rotate-90'}">▶</span>
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
		</div>
	{/each}
</div>
