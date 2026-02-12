<script lang="ts">
	import type { AutoNextPlanDetailResponse } from '$lib/api';

	interface Props {
		detail: AutoNextPlanDetailResponse;
		onClose?: () => void;
	}

	let { detail, onClose }: Props = $props();

	let expandedPhases = $state<Set<number>>(new Set(
		detail.phases.map((_, i) => i)
	));

	function togglePhase(index: number) {
		const next = new Set(expandedPhases);
		if (next.has(index)) {
			next.delete(index);
		} else {
			next.add(index);
		}
		expandedPhases = next;
	}
</script>

<div class="bg-white rounded-lg border p-4">
	<div class="flex items-center justify-between mb-3">
		<div class="flex items-center gap-2 min-w-0">
			<h3 class="font-semibold text-sm truncate" title={detail.path}>{detail.filename}</h3>
			<span class="text-xs text-gray-500 shrink-0">
				{detail.progress.done}/{detail.progress.total} ({detail.progress.percent}%)
			</span>
		</div>
		{#if onClose}
			<button
				class="text-gray-400 hover:text-gray-600 text-lg leading-none shrink-0 ml-2"
				onclick={onClose}
				title="닫기"
			>&times;</button>
		{/if}
	</div>

	<!-- Progress bar -->
	<div class="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-3">
		<div
			class="h-full rounded-full transition-all {detail.progress.percent >= 100 ? 'bg-green-500' : 'bg-blue-500'}"
			style="width: {detail.progress.percent}%"
		></div>
	</div>

	<!-- Phases -->
	<div class="space-y-2 max-h-[500px] overflow-y-auto">
		{#each detail.phases as phase, i}
			<div class="border rounded">
				<!-- Phase header (accordion) -->
				<button
					class="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gray-50 transition-colors"
					onclick={() => togglePhase(i)}
				>
					<span class="text-sm font-medium">{phase.name}</span>
					<div class="flex items-center gap-2 shrink-0">
						<span class="text-xs text-gray-500">{phase.done_count}/{phase.total_count}</span>
						<svg
							class="w-4 h-4 text-gray-400 transition-transform {expandedPhases.has(i) ? 'rotate-180' : ''}"
							viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
						>
							<path d="M6 9l6 6 6-6" />
						</svg>
					</div>
				</button>

				<!-- Phase items -->
				{#if expandedPhases.has(i)}
					<div class="border-t px-3 py-2 space-y-1.5">
						{#each phase.items as item}
							<!-- 상위 항목 -->
							<div class="flex items-start gap-2 {item.checked ? 'opacity-50' : ''}">
								<span class="text-xs mt-0.5 shrink-0">{item.checked ? '✓' : '○'}</span>
								<span class="text-sm {item.checked ? 'line-through text-gray-400' : 'font-medium'}">
									{item.text}
								</span>
							</div>
							<!-- 하위 항목 -->
							{#each item.children as child}
								<div class="flex items-start gap-2 ml-5 {child.checked ? 'opacity-50' : ''}">
									<span class="text-xs mt-0.5 shrink-0">{child.checked ? '✓' : '○'}</span>
									<span class="text-xs {child.checked ? 'line-through text-gray-400' : 'text-gray-700'}">
										{child.text}
									</span>
								</div>
							{/each}
						{/each}
					</div>
				{/if}
			</div>
		{/each}
	</div>
</div>
