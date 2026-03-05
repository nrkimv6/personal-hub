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

<div class="flex flex-col gap-2 h-full min-h-0 overflow-y-auto">
	{#if !planPath}
		<div class="text-center py-8 text-xs text-gray-400">
			Plan을 선택하면 항목이 표시됩니다
		</div>
	{:else if loading}
		<div class="flex items-center justify-center py-8">
			<div class="animate-spin rounded-full h-5 w-5 border-b-2 border-gray-400"></div>
		</div>
	{:else if error}
		<div class="text-xs text-red-500 py-4 text-center">{error}</div>
	{:else if detail}
		<!-- Header -->
		<div class="flex items-center justify-between px-1 shrink-0">
			<span class="text-[10px] text-gray-500 font-mono truncate max-w-[200px]">{detail.filename}</span>
			<span class="text-[10px] font-mono text-gray-500">{detail.progress.done}/{detail.progress.total} ({detail.progress.percent}%)</span>
		</div>

		<!-- Summary card -->
		{#if detail.summary}
			<div class="bg-blue-50 border border-blue-100 rounded-md px-3 py-2 shrink-0">
				<button
					class="w-full text-left"
					onclick={() => (summaryExpanded = !summaryExpanded)}
				>
					<div class="flex items-center justify-between gap-2">
						<span class="text-[10px] font-medium text-blue-600 shrink-0">요약</span>
						<svg
							class="w-3 h-3 text-blue-400 shrink-0 transition-transform {summaryExpanded ? 'rotate-180' : ''}"
							viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
						>
							<polyline points="6 9 12 15 18 9" />
						</svg>
					</div>
					{#if !summaryExpanded}
						<p class="text-[10px] text-gray-500 mt-1 line-clamp-1">{detail.summary.split('\n')[0]}</p>
					{/if}
				</button>
				{#if summaryExpanded}
					<p class="text-[11px] text-gray-600 mt-1.5 leading-relaxed whitespace-pre-wrap">{detail.summary}</p>
				{/if}
			</div>
		{/if}

		<!-- Phases -->
		{#each detail.phases as phase}
			<div class="border rounded-md overflow-hidden">
				<!-- Phase header -->
				<div class="flex items-center justify-between px-3 py-1.5 bg-gray-50 border-b">
					<span class="text-[11px] font-medium text-gray-700 truncate">{phase.name}</span>
					<span class="text-[10px] font-mono text-gray-400 shrink-0 ml-2">{phase.done_count}/{phase.total_count}</span>
				</div>

				<!-- Items -->
				<div class="divide-y">
					{#each phase.items as item}
						<div class="px-3 py-2 flex items-start gap-2">
							<!-- Checkbox icon -->
							<span class="shrink-0 mt-0.5">
								{#if item.checked}
									<svg class="w-3.5 h-3.5 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
										<polyline points="20 6 9 17 4 12" />
									</svg>
								{:else}
									<svg class="w-3.5 h-3.5 text-gray-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
										<rect x="3" y="3" width="18" height="18" rx="2" />
									</svg>
								{/if}
							</span>

							<div class="flex flex-col gap-0.5 min-w-0 flex-1">
								<span class="text-[11px] leading-relaxed {item.checked ? 'text-gray-400 line-through' : 'text-gray-700'}">{item.text}</span>
								{#if item.file_path}
									<span class="text-[10px] text-blue-500 font-mono truncate">{item.file_path}</span>
								{/if}

								<!-- Sub-items -->
								{#if item.children.length > 0}
									<div class="mt-1 flex flex-col gap-1 pl-2 border-l border-gray-100">
										{#each item.children as child}
											<div class="flex items-start gap-1.5">
												<span class="shrink-0 mt-0.5">
													{#if child.checked}
														<svg class="w-3 h-3 text-green-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
															<polyline points="20 6 9 17 4 12" />
														</svg>
													{:else}
														<svg class="w-3 h-3 text-gray-200" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
															<rect x="3" y="3" width="18" height="18" rx="2" />
														</svg>
													{/if}
												</span>
												<span class="text-[10px] leading-relaxed {child.checked ? 'text-gray-300 line-through' : 'text-gray-500'}">{child.text}</span>
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
	{:else}
		<div class="text-center py-8 text-xs text-gray-400">항목이 없습니다</div>
	{/if}
</div>
