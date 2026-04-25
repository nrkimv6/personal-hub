<script lang="ts">
	import type { SearchHistoryItem, SearchSuggestionItem } from '$lib/types/fileSearch';
	import { Clock, Sparkles } from 'lucide-svelte';

	interface Props {
		history: SearchHistoryItem[];
		suggestions: SearchSuggestionItem[];
		loading?: boolean;
		error?: string;
		onsuggestion: (query: string) => void;
		onhistory: (item: SearchHistoryItem) => void;
	}

	let { history, suggestions, loading = false, error = '', onsuggestion, onhistory }: Props = $props();

	const MODE_LABELS: Record<string, string> = {
		filename: '파일명',
		content: '내용',
		both: '둘다'
	};

	function formatWhen(ts: string) {
		// created_at는 "YYYY-MM-DD HH:MM:SS" 고정 포맷
		if (!ts) return '';
		const parts = ts.split(' ');
		return parts.length >= 2 ? `${parts[0]} ${parts[1].slice(0, 5)}` : ts;
	}
</script>

<div class="rounded-lg border border-border bg-card px-4 py-3 space-y-3">
	<div class="flex items-start justify-between gap-4">
		<div class="space-y-1">
			<div class="text-xs font-medium text-muted-foreground flex items-center gap-2">
				<Sparkles size={14} class="opacity-70" /> 추천 검색어
			</div>
			{#if loading}
				<div class="flex flex-wrap gap-2">
					<div class="h-7 w-20 rounded-full border border-border bg-muted/50 animate-skeleton-shimmer"></div>
					<div class="h-7 w-28 rounded-full border border-border bg-muted/50 animate-skeleton-shimmer"></div>
					<div class="h-7 w-24 rounded-full border border-border bg-muted/50 animate-skeleton-shimmer"></div>
				</div>
			{:else if suggestions.length === 0}
				<div class="text-xs text-muted-foreground">추천 검색어가 없습니다.</div>
			{:else}
				<div class="flex flex-wrap gap-2">
					{#each suggestions as s (s.query)}
						<button
							onclick={() => onsuggestion(s.query)}
							class="flex items-center gap-1 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium
								   text-muted-foreground hover:text-foreground hover:border-primary/40 hover:bg-muted/40 transition-colors"
							title={`${s.count}회 (최근: ${formatWhen(s.last_used_at)})`}
						>
							<span>{s.query}</span>
							<span class="opacity-60">{s.count}</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<div class="space-y-1">
		<div class="text-xs font-medium text-muted-foreground flex items-center gap-2">
			<Clock size={14} class="opacity-70" /> 최근 검색
		</div>
		{#if error}
			<div class="text-xs text-destructive">{error}</div>
		{:else if loading}
			<div class="space-y-2">
				<div class="h-10 rounded-md border border-border bg-muted/50 animate-skeleton-shimmer"></div>
				<div class="h-10 rounded-md border border-border bg-muted/50 animate-skeleton-shimmer"></div>
			</div>
		{:else if history.length === 0}
			<div class="text-xs text-muted-foreground">최근 검색 이력이 없습니다.</div>
		{:else}
			<div class="space-y-2">
				{#each history as h (h.search_id)}
					<button
						onclick={() => onhistory(h)}
						class="group w-full rounded-md border border-border bg-background px-3 py-2 text-left
							   hover:bg-muted/40 hover:border-primary/30 transition-colors"
					>
						<div class="flex items-center justify-between gap-3">
							<div class="min-w-0">
								<div class="text-sm font-medium truncate">{h.query}</div>
								<div class="text-xs text-muted-foreground">
									{MODE_LABELS[h.mode] ?? h.mode} · {h.total_count}건 · {formatWhen(h.created_at)}
								</div>
							</div>
						</div>
						{#if h.sample_files.length > 0}
							<div class="mt-1 text-[11px] text-muted-foreground/80 truncate">
								{h.sample_files.join(', ')}
							</div>
						{/if}
					</button>
				{/each}
			</div>
		{/if}
	</div>
</div>

