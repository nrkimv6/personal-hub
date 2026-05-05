<script lang="ts">
	import { devRunnerPlanApi } from '$lib/api';
	import type { DevRunnerPlanDetailResponse as PlanDetailResponse } from '$lib/api';
	import { encodePathToBase64 } from '$lib/utils/encoding';

	interface Props {
		planPath?: string | null;
		refreshTick?: number;
	}

	let { planPath = null, refreshTick = 0 }: Props = $props();

	let detail = $state<PlanDetailResponse | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let summaryExpanded = $state(false);

	async function fetchItems(path: string) {
		loading = true;
		error = null;
		try {
			const encoded = encodePathToBase64(path);
			detail = await devRunnerPlanApi.items(encoded);
		} catch (e) {
			error = e instanceof Error ? e.message : '로딩 실패';
			detail = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (planPath) {
			void fetchItems(planPath);
		} else {
			detail = null;
		}
	});

	// 외부 refresh 트리거 (SSE plan_changed 이벤트)
	$effect(() => {
		if (refreshTick > 0 && planPath) {
			void fetchItems(planPath);
		}
	});

</script>

<div class="flex-1 min-h-0 overflow-y-auto dr-scrollbar-thin">
	{#if !planPath}
		<div class="text-center py-8 text-xs text-muted-foreground">
			Plan을 선택하면 항목이 표시됩니다
		</div>
	{:else if loading}
		<div class="flex items-center justify-center py-8">
			<div class="animate-spin rounded-full h-5 w-5 border-b-2 border-gray-400"></div>
		</div>
	{:else if error}
		<div class="text-xs text-red-500 py-4 text-center">{error}</div>
	{:else if detail}
		<div class="flex flex-col gap-2 pb-1 pr-1">
			<!-- Header -->
			<div class="flex items-center justify-between px-1 shrink-0">
				<span class="text-[10px] text-muted-foreground font-mono truncate max-w-[200px]">{detail.filename}</span>
				<span class="text-[10px] font-mono text-muted-foreground">{detail.progress.done}/{detail.progress.total} ({detail.progress.percent}%)</span>
			</div>

			<!-- Summary card -->
			{#if detail.summary}
				<div class="bg-blue-50/80 border border-blue-100 rounded-lg p-3 shrink-0 transition-all">
					<button
						class="w-full text-left"
						onclick={() => (summaryExpanded = !summaryExpanded)}
					>
						<div class="flex items-center justify-between gap-2">
							<span class="text-[10px] font-bold text-blue-600 uppercase tracking-wider shrink-0">Summary</span>
							<svg
								class="w-3.5 h-3.5 text-blue-400 shrink-0 transition-transform duration-300 {summaryExpanded ? 'rotate-180' : ''}"
								viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
							>
								<polyline points="6 9 12 15 18 9" />
							</svg>
						</div>
						{#if !summaryExpanded}
							<p class="text-[11px] text-blue-800 mt-1.5 line-clamp-2 leading-relaxed break-words">{detail.summary}</p>
						{/if}
					</button>
					{#if summaryExpanded}
						<div class="mt-2.5 pt-2.5 border-t border-blue-100/50">
							<p class="text-[11px] text-blue-900 leading-relaxed break-words whitespace-pre-wrap">{detail.summary}</p>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Phases -->
			{#each detail.phases as phase}
				<div class="border border-border rounded-lg overflow-hidden bg-card text-card-foreground shadow-sm shrink-0">
					<!-- Phase header -->
					<div class="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border">
						<span class="text-[11px] font-bold text-foreground truncate">{phase.name}</span>
						<span class="text-[10px] font-mono font-medium text-muted-foreground shrink-0 ml-2 bg-muted px-1.5 py-0.5 rounded">{phase.done_count}/{phase.total_count}</span>
					</div>

					<!-- Items -->
					<div class="divide-y divide-border">
						{#each phase.items as item}
							<div class="px-3 py-2.5 flex items-start gap-2.5 hover:bg-muted/50 transition-colors">
								<!-- Checkbox icon -->
								<span class="shrink-0 mt-0.5">
									{#if item.checked}
										<div class="w-4 h-4 rounded bg-green-500 flex items-center justify-center">
											<svg class="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
												<polyline points="20 6 9 17 4 12" />
											</svg>
										</div>
									{:else}
										<div class="w-4 h-4 rounded border-2 border-border bg-background"></div>
									{/if}
								</span>

								<div class="flex flex-col gap-1 min-w-0 flex-1">
									<span class="text-[12px] leading-relaxed break-words whitespace-pre-wrap {item.checked ? 'text-muted-foreground line-through' : 'text-foreground'}">{item.text}</span>
									{#if item.file_path}
										<div class="flex items-center gap-1.5">
											<svg class="w-2.5 h-2.5 text-blue-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
											<span class="text-[10px] text-blue-500 font-mono truncate font-medium">{item.file_path}</span>
										</div>
									{/if}

									<!-- Sub-items -->
									{#if item.children.length > 0}
										<div class="mt-2 flex flex-col gap-1.5 pl-3 border-l-2 border-border">
											{#each item.children as child}
												<div class="flex items-start gap-2">
													<span class="shrink-0 mt-1">
														{#if child.checked}
															<svg class="w-3 h-3 text-green-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
																<polyline points="20 6 9 17 4 12" />
															</svg>
														{:else}
															<div class="w-2.5 h-2.5 rounded-sm border border-border"></div>
														{/if}
													</span>
													<span class="min-w-0 flex-1 text-[11px] leading-relaxed break-words whitespace-pre-wrap {child.checked ? 'text-muted-foreground/80 line-through' : 'text-muted-foreground'}">{child.text}</span>
												</div>
											{/each}
										</div>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<div class="text-center py-8 text-xs text-muted-foreground">항목이 없습니다</div>
	{/if}
</div>
