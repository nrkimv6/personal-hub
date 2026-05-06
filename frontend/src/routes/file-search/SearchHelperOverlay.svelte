<script lang="ts">
	import type { FrequentSearchComboItem, SearchHistoryItem } from '$lib/types/fileSearch';
	import { Clock, Sparkles, X } from 'lucide-svelte';

	export type SearchHelperTab = 'combos' | 'history';

	interface Props {
		open: boolean;
		activeTab: SearchHelperTab;
		history: SearchHistoryItem[];
		frequentCombos: FrequentSearchComboItem[];
		historyLoading?: boolean;
		comboLoading?: boolean;
		historyError?: string;
		comboError?: string;
		onclose: () => void;
		ontabchange: (tab: SearchHelperTab) => void;
		oncombo: (item: FrequentSearchComboItem) => void;
		onhistory: (item: SearchHistoryItem) => void;
	}

	let {
		open,
		activeTab,
		history,
		frequentCombos,
		historyLoading = false,
		comboLoading = false,
		historyError = '',
		comboError = '',
		onclose,
		ontabchange,
		oncombo,
		onhistory
	}: Props = $props();

	const MODE_LABELS: Record<string, string> = {
		filename: '파일명',
		content: '내용',
		both: '둘 다'
	};

	function formatWhen(ts: string) {
		if (!ts) return '';
		const parts = ts.split(' ');
		return parts.length >= 2 ? `${parts[0]} ${parts[1].slice(0, 5)}` : ts;
	}

	function handleBackdropClick(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			onclose();
		}
	}
</script>

<svelte:window
	onkeydown={(event) => {
		if (open && event.key === 'Escape') onclose();
	}}
/>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-end justify-center bg-black/55 p-3 backdrop-blur-[2px] sm:items-center sm:p-4"
		role="dialog"
		aria-modal="true"
		aria-label="탐색도우미"
		tabindex="-1"
		onclick={handleBackdropClick}
		onkeydown={(event) => {
			if (event.key === 'Escape') onclose();
		}}
	>
		<div class="flex max-h-[90vh] w-[min(960px,100%)] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
			<div class="flex flex-wrap items-start gap-3 border-b border-border px-4 py-3">
				<div class="min-w-0 flex-1">
					<div class="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
						탐색 도우미
					</div>
					<h2 class="mt-1 text-base font-semibold text-foreground">최근 검색과 자주 쓰는 조합</h2>
					<p class="mt-1 text-sm text-muted-foreground">
						검색을 다시 입력하지 않고 최근 문맥을 바로 복원합니다.
					</p>
				</div>

				<div class="ml-auto flex shrink-0 items-center gap-2">
					<div class="inline-flex rounded-full border border-border bg-background p-1">
						<button
							type="button"
							onclick={() => ontabchange('combos')}
							class="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-medium transition-colors {activeTab === 'combos'
								? 'bg-primary text-primary-foreground'
								: 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'}"
						>
							<Sparkles size={14} />
							자주 쓰는 조합
						</button>
						<button
							type="button"
							onclick={() => ontabchange('history')}
							class="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-medium transition-colors {activeTab === 'history'
								? 'bg-primary text-primary-foreground'
								: 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'}"
						>
							<Clock size={14} />
							최근 검색
						</button>
					</div>
					<button
						type="button"
						onclick={onclose}
						class="rounded-md border border-border bg-background p-1.5 text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
						aria-label="탐색도우미 닫기"
					>
						<X size={16} />
					</button>
				</div>
			</div>

			<div class="min-h-0 flex-1 overflow-auto px-4 py-4">
				{#if activeTab === 'combos'}
					<div class="space-y-3">
						{#if comboError}
							<div class="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
								{comboError}
							</div>
						{:else if comboLoading}
							<div class="space-y-2">
								<div class="h-20 rounded-xl border border-border bg-muted/50 animate-skeleton-shimmer"></div>
								<div class="h-20 rounded-xl border border-border bg-muted/50 animate-skeleton-shimmer"></div>
								<div class="h-20 rounded-xl border border-border bg-muted/50 animate-skeleton-shimmer"></div>
							</div>
						{:else if frequentCombos.length === 0}
							<div class="rounded-xl border border-dashed border-border bg-background px-4 py-8 text-sm text-muted-foreground">
								자주 쓰는 조합이 없습니다. 먼저 검색을 실행하면 이 영역에서 바로 다시 열 수 있습니다.
							</div>
						{:else}
							<div class="grid gap-3 sm:grid-cols-2">
								{#each frequentCombos as combo (`${combo.label}-${combo.last_used_at}`)}
									<button
										type="button"
										onclick={() => oncombo(combo)}
										class="group rounded-xl border border-border bg-background px-4 py-3 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
									>
										<div class="flex items-start justify-between gap-3">
											<div class="min-w-0 space-y-1">
												<div class="truncate text-sm font-semibold text-foreground">{combo.label}</div>
												<div class="text-xs text-muted-foreground">
													{combo.count}회 사용 · 최근 {formatWhen(combo.last_used_at)}
												</div>
											</div>
										</div>
										{#if combo.summary_tokens.length > 0}
											<div class="mt-3 flex flex-wrap gap-1.5">
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
					<div class="space-y-3">
						{#if historyError}
							<div class="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
								{historyError}
							</div>
						{:else if historyLoading}
							<div class="space-y-2">
								<div class="h-14 rounded-xl border border-border bg-muted/50 animate-skeleton-shimmer"></div>
								<div class="h-14 rounded-xl border border-border bg-muted/50 animate-skeleton-shimmer"></div>
								<div class="h-14 rounded-xl border border-border bg-muted/50 animate-skeleton-shimmer"></div>
							</div>
						{:else if history.length === 0}
							<div class="rounded-xl border border-dashed border-border bg-background px-4 py-8 text-sm text-muted-foreground">
								최근 검색 이력이 없습니다.
							</div>
						{:else}
							<div class="space-y-2">
								{#each history as item (item.search_id)}
									<button
										type="button"
										onclick={() => onhistory(item)}
										class="group w-full rounded-xl border border-border bg-background px-4 py-3 text-left transition-colors hover:border-primary/30 hover:bg-muted/40"
									>
										<div class="flex items-center justify-between gap-3">
											<div class="min-w-0">
												<div class="truncate text-sm font-semibold text-foreground">{item.query}</div>
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
		</div>
	</div>
{/if}
