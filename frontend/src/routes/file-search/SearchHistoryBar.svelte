<script lang="ts">
	import type { FrequentSearchComboItem, SearchHistoryItem } from '$lib/types/fileSearch';
	import { Clock, Sparkles } from 'lucide-svelte';

	type HistoryTab = 'combos' | 'history';

	interface Props {
		history: SearchHistoryItem[];
		frequentCombos: FrequentSearchComboItem[];
		historyLoading?: boolean;
		comboLoading?: boolean;
		historyError?: string;
		comboError?: string;
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
		oncombo,
		onhistory
	}: Props = $props();

	let activeTab: HistoryTab = $state('combos');

	const MODE_LABELS: Record<string, string> = {
		filename: '파일명',
		content: '내용',
		both: '둘다'
	};

	function formatWhen(ts: string) {
		if (!ts) return '';
		const parts = ts.split(' ');
		return parts.length >= 2 ? `${parts[0]} ${parts[1].slice(0, 5)}` : ts;
	}
</script>

<div class="space-y-3 rounded-lg border border-border bg-card px-4 py-3">
	<div class="flex items-center justify-between gap-4">
		<div class="space-y-1">
			<div class="text-xs font-medium text-muted-foreground">탐색 도우미</div>
			<div class="text-sm font-semibold text-foreground">최근 검색과 자주 쓰는 조합</div>
		</div>
		<div class="inline-flex rounded-full border border-border bg-background p-1">
			<button
				type="button"
				onclick={() => (activeTab = 'combos')}
				class="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-medium transition-colors {activeTab === 'combos'
					? 'bg-primary text-primary-foreground'
					: 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'}"
			>
				<Sparkles size={14} />
				자주 쓰는 조합
			</button>
			<button
				type="button"
				onclick={() => (activeTab = 'history')}
				class="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-medium transition-colors {activeTab === 'history'
					? 'bg-primary text-primary-foreground'
					: 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'}"
			>
				<Clock size={14} />
				최근 검색
			</button>
		</div>
	</div>

	{#if activeTab === 'combos'}
		<div class="space-y-2">
			{#if comboError}
				<div class="text-xs text-destructive">{comboError}</div>
			{:else if comboLoading}
				<div class="space-y-2">
					<div class="h-16 rounded-md border border-border bg-muted/50 animate-skeleton-shimmer"></div>
					<div class="h-16 rounded-md border border-border bg-muted/50 animate-skeleton-shimmer"></div>
				</div>
			{:else if frequentCombos.length === 0}
				<div class="rounded-md border border-dashed border-border bg-background px-4 py-5 text-sm text-muted-foreground">
					자주 쓰는 조합이 없습니다. 먼저 검색을 몇 번 실행하거나 프리셋과 필터를 조합해 보세요.
				</div>
			{:else}
				<div class="max-h-80 space-y-2 overflow-y-auto pr-1">
					{#each frequentCombos as combo (`${combo.label}-${combo.last_used_at}`)}
						<button
							type="button"
							onclick={() => oncombo(combo)}
							class="group w-full rounded-md border border-border bg-background px-3 py-2 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
						>
							<div class="flex items-start justify-between gap-3">
								<div class="min-w-0 space-y-1">
									<div class="truncate text-sm font-medium">{combo.label}</div>
									<div class="text-xs text-muted-foreground">
										{combo.count}회 사용 · 최근 {formatWhen(combo.last_used_at)}
									</div>
								</div>
							</div>
							{#if combo.summary_tokens.length > 0}
								<div class="mt-2 flex flex-wrap gap-1.5">
									{#each combo.summary_tokens as token (`${combo.label}-${token}`)}
										<span class="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">
											{token}
										</span>
									{/each}
								</div>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{:else}
		<div class="space-y-2">
			{#if historyError}
				<div class="text-xs text-destructive">{historyError}</div>
			{:else if historyLoading}
				<div class="space-y-2">
					<div class="h-10 rounded-md border border-border bg-muted/50 animate-skeleton-shimmer"></div>
					<div class="h-10 rounded-md border border-border bg-muted/50 animate-skeleton-shimmer"></div>
				</div>
			{:else if history.length === 0}
				<div class="text-xs text-muted-foreground">최근 검색 이력이 없습니다.</div>
			{:else}
				<div class="max-h-80 space-y-2 overflow-y-auto pr-1">
					{#each history as item (item.search_id)}
						<button
							type="button"
							onclick={() => onhistory(item)}
							class="group w-full rounded-md border border-border bg-background px-3 py-2 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
						>
							<div class="flex items-center justify-between gap-3">
								<div class="min-w-0">
									<div class="truncate text-sm font-medium">{item.query}</div>
									<div class="text-xs text-muted-foreground">
										{MODE_LABELS[item.mode] ?? item.mode} · {item.total_count}건 · {formatWhen(item.created_at)}
									</div>
								</div>
							</div>
							{#if item.sample_files.length > 0}
								<div class="mt-1 truncate text-[11px] text-muted-foreground/80">
									{item.sample_files.join(', ')}
								</div>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
