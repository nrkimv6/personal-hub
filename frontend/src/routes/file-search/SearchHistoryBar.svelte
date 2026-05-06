<script lang="ts">
	import type { FrequentSearchComboItem, SearchHistoryItem } from '$lib/types/fileSearch';
	import type { SearchHelperTab } from './SearchHelperOverlay.svelte';
	import { ArrowUpRight, Clock, Sparkles } from 'lucide-svelte';

	interface Props {
		history: SearchHistoryItem[];
		frequentCombos: FrequentSearchComboItem[];
		historyLoading?: boolean;
		comboLoading?: boolean;
		historyError?: string;
		comboError?: string;
		onopen: (tab: SearchHelperTab) => void;
		oncombo: (item: FrequentSearchComboItem) => void;
		onhistory: (item: SearchHistoryItem) => void;
	}

	let {
		history,
		frequentCombos,
		historyLoading = false,
		comboLoading = false,
		historyError = '',
		comboError = '',
		onopen,
		oncombo,
		onhistory
	}: Props = $props();

	const comboPreview = $derived(frequentCombos.slice(0, 2));
	const historyPreview = $derived(history.slice(0, 2));

	function describeCombo(item: FrequentSearchComboItem): string {
		if (item.summary_tokens.length > 0) {
			return item.summary_tokens.slice(0, 3).join(' · ');
		}
		return `${item.count}회 사용`;
	}

	function describeHistory(item: SearchHistoryItem): string {
		const path = item.request.paths?.[0];
		if (path) {
			const normalized = path.replace(/\\/g, '/');
			const parts = normalized.split('/').filter(Boolean);
			return parts.length > 0 ? parts[parts.length - 1] : normalized;
		}
		return `${item.total_count}건 결과`;
	}
</script>

<div class="rounded-2xl border border-border bg-card px-4 py-3">
	<div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
		<div class="space-y-1">
			<div class="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">탐색 도우미</div>
			<div class="text-sm font-semibold text-foreground">결과를 가리지 않고 최근 문맥만 빠르게 불러옵니다</div>
		</div>

		<div class="flex flex-wrap items-center gap-2">
			<button
				type="button"
				onclick={() => onopen('combos')}
				aria-label="자주 쓰는 조합 열기"
				class="inline-flex items-center gap-1 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
			>
				<Sparkles size={14} />
				조합 {frequentCombos.length}
			</button>
			<button
				type="button"
				onclick={() => onopen('history')}
				aria-label="최근 검색 열기"
				class="inline-flex items-center gap-1 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
			>
				<Clock size={14} />
				최근 {history.length}
			</button>
		</div>
	</div>

	<div class="mt-3 grid gap-2 lg:grid-cols-2">
		<div class="rounded-xl border border-border/70 bg-background/80 p-3">
			<div class="mb-2 flex items-center justify-between gap-3">
				<div class="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
					<Sparkles size={14} />
					자주 쓰는 조합
				</div>
				<button
					type="button"
					onclick={() => onopen('combos')}
					aria-label="자주 쓰는 조합 전체 보기"
					class="text-xs font-medium text-primary transition-colors hover:opacity-80"
				>
					전체 보기
				</button>
			</div>

			{#if comboError}
				<div class="text-xs text-destructive">{comboError}</div>
			{:else if comboLoading}
				<div class="space-y-2">
					<div class="h-10 rounded-lg border border-border bg-muted/50 animate-skeleton-shimmer"></div>
					<div class="h-10 rounded-lg border border-border bg-muted/50 animate-skeleton-shimmer"></div>
				</div>
			{:else if comboPreview.length === 0}
				<div class="text-xs text-muted-foreground">자주 쓰는 조합이 아직 없습니다.</div>
			{:else}
				<div class="space-y-2">
					{#each comboPreview as combo (`combo-${combo.label}-${combo.last_used_at}`)}
						<button
							type="button"
							onclick={() => oncombo(combo)}
							class="flex w-full items-start justify-between gap-3 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
						>
							<div class="min-w-0">
								<div class="truncate text-sm font-medium text-foreground">{combo.label}</div>
								<div class="truncate text-[11px] text-muted-foreground">{describeCombo(combo)}</div>
							</div>
							<ArrowUpRight size={14} class="mt-0.5 shrink-0 text-muted-foreground" />
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<div class="rounded-xl border border-border/70 bg-background/80 p-3">
			<div class="mb-2 flex items-center justify-between gap-3">
				<div class="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
					<Clock size={14} />
					최근 검색
				</div>
				<button
					type="button"
					onclick={() => onopen('history')}
					aria-label="최근 검색 전체 보기"
					class="text-xs font-medium text-primary transition-colors hover:opacity-80"
				>
					전체 보기
				</button>
			</div>

			{#if historyError}
				<div class="text-xs text-destructive">{historyError}</div>
			{:else if historyLoading}
				<div class="space-y-2">
					<div class="h-10 rounded-lg border border-border bg-muted/50 animate-skeleton-shimmer"></div>
					<div class="h-10 rounded-lg border border-border bg-muted/50 animate-skeleton-shimmer"></div>
				</div>
			{:else if historyPreview.length === 0}
				<div class="text-xs text-muted-foreground">최근 검색 이력이 없습니다.</div>
			{:else}
				<div class="space-y-2">
					{#each historyPreview as item (`history-${item.search_id}`)}
						<button
							type="button"
							onclick={() => onhistory(item)}
							class="flex w-full items-start justify-between gap-3 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
						>
							<div class="min-w-0">
								<div class="truncate text-sm font-medium text-foreground">{item.query}</div>
								<div class="truncate text-[11px] text-muted-foreground">{describeHistory(item)}</div>
							</div>
							<ArrowUpRight size={14} class="mt-0.5 shrink-0 text-muted-foreground" />
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>
</div>
