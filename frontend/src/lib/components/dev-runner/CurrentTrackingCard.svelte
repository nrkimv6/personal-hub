<script lang="ts">
	import type { CurrentTrackingResponse } from '$lib/api/dev-runner';

	interface Props {
		tracking: CurrentTrackingResponse | null;
	}

	let { tracking }: Props = $props();

	// confidence별 색상
	function badgeClass(confidence: string, stale: boolean): string {
		if (stale) return 'text-muted-foreground bg-muted border border-border';
		if (confidence === 'HIGH') return 'text-success bg-success/10 border border-success/20';
		if (confidence === 'MEDIUM') return 'text-warning bg-warning/10 border border-warning/20';
		return 'text-muted-foreground bg-muted border border-border';
	}

	function labelText(confidence: string, stale: boolean): string {
		if (stale) return 'STALE';
		return confidence;
	}
</script>

{#if tracking}
	<div class="bg-card rounded-md border border-primary/20 px-3 py-2">
		<div class="mb-1 flex items-center gap-2">
			<svg class="w-3 h-3 text-primary" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10"/>
				<circle cx="12" cy="12" r="6"/>
				<circle cx="12" cy="12" r="2"/>
			</svg>
			<span class="text-[10px] font-mono font-bold uppercase text-purple-600 dark:text-purple-400">Tracking</span>
			<span
				class="rounded px-1.5 py-0.5 text-[10px] font-mono font-bold {badgeClass(tracking.confidence, tracking.stale)}"
			>
				{labelText(tracking.confidence, tracking.stale)}
			</span>
			{#if tracking.line_num != null}
				<span class="text-[10px] font-mono text-muted-foreground">L{tracking.line_num}</span>
			{/if}
			{#if tracking.stale}
				<span class="text-[10px] font-mono text-muted-foreground/60">· stale</span>
			{/if}
		</div>
		<p class="truncate text-sm font-medium text-foreground" title={tracking.text}>
			{tracking.text}
		</p>
		{#if tracking.plan_file}
			<p class="mt-0.5 truncate text-xs text-muted-foreground font-mono" title={tracking.plan_file}>
				{tracking.plan_file.split('/').pop() ?? tracking.plan_file}
			</p>
		{/if}
	</div>
{/if}
