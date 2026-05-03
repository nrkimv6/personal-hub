<script lang="ts">
	import type { DevRunnerPlanDetailResponse } from '$lib/api';

	interface Props {
		detail: DevRunnerPlanDetailResponse;
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

<div class="bg-card text-card-foreground rounded-lg border border-border p-4 {detail.status === '구현완료' ? 'opacity-50' : ''}">
	<div class="flex items-center justify-between mb-3">
		<div class="flex items-center gap-2 min-w-0">
			<h3 class="font-semibold text-sm truncate" title={detail.path}>{detail.filename}</h3>
			{#if detail.status === '구현완료'}
				<span class="text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded bg-green-100 text-green-700 shrink-0">구현완료</span>
			{/if}
			<span class="text-xs text-muted-foreground shrink-0">
				{detail.progress.done}/{detail.progress.total} ({detail.progress.percent}%)
			</span>
		</div>
		{#if onClose}
			<button
				class="text-muted-foreground hover:text-foreground text-lg leading-none shrink-0 ml-2"
				onclick={onClose}
				title="닫기"
			>&times;</button>
		{/if}
	</div>

	<!-- Progress bar -->
	<div class="h-1.5 bg-muted rounded-full overflow-hidden mb-3">
		<div
			class="h-full rounded-full transition-all {detail.progress.percent >= 100 ? 'bg-green-500' : 'bg-blue-500'}"
			style="width: {detail.progress.percent}%"
		></div>
	</div>

	<!-- Phases -->
	<div class="space-y-2 max-h-[300px] sm:max-h-[500px] overflow-y-auto">
		{#each detail.phases as phase, i}
			<div class="border border-border rounded">
				<!-- Phase header (accordion) -->
				<button
					class="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-muted transition-colors"
					onclick={() => togglePhase(i)}
				>
					<span class="text-sm font-medium">{phase.name}</span>
					<div class="flex items-center gap-2 shrink-0">
						<span class="text-xs text-muted-foreground">{phase.done_count}/{phase.total_count}</span>
						<svg
							class="w-4 h-4 text-muted-foreground transition-transform {expandedPhases.has(i) ? 'rotate-180' : ''}"
							viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
						>
							<path d="M6 9l6 6 6-6" />
						</svg>
					</div>
				</button>

				<!-- Phase items -->
				{#if expandedPhases.has(i)}
					<div class="border-t border-border px-3 py-2 space-y-1.5">
						{#each phase.items as item}
							<!-- 상위 항목 -->
							<div class="flex items-start gap-2 {item.checked ? 'opacity-50' : ''}">
								<span class="text-xs mt-0.5 shrink-0">{item.checked ? '완' : '○'}</span>
								<span class="text-sm {item.checked ? 'line-through text-muted-foreground' : 'font-medium text-foreground'}">
									{item.text}
								</span>
							</div>
							<!-- 하위 항목 -->
							{#each item.children as child}
								<div class="flex items-start gap-2 ml-5 {child.checked ? 'opacity-50' : ''}">
									<span class="text-xs mt-0.5 shrink-0">{child.checked ? '완' : '○'}</span>
									<span class="text-xs {child.checked ? 'line-through text-muted-foreground' : 'text-muted-foreground'}">
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
