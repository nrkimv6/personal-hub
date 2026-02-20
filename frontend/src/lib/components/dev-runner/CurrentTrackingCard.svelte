<script lang="ts">
	import type { CurrentTrackingResponse } from '$lib/api/dev-runner';

	interface Props {
		tracking: CurrentTrackingResponse | null;
	}

	let { tracking }: Props = $props();

	// confidence별 색상
	function badgeClass(confidence: string, stale: boolean): string {
		if (stale) return 'text-gray-400 bg-gray-500/20 border border-gray-500/30';
		if (confidence === 'HIGH') return 'text-green-400 bg-green-500/20 border border-green-500/30';
		if (confidence === 'MEDIUM') return 'text-yellow-400 bg-yellow-500/20 border border-yellow-500/30';
		return 'text-gray-400 bg-gray-500/20 border border-gray-500/30';
	}

	function labelText(confidence: string, stale: boolean): string {
		if (stale) return 'STALE';
		return confidence;
	}
</script>

{#if tracking}
	<div class="mb-3 rounded-lg border border-purple-500/20 bg-purple-500/10 px-3 py-2">
		<div class="mb-1 flex items-center gap-2">
			<span class="text-xs font-medium text-purple-400">추적 중</span>
			<span
				class="rounded px-1.5 py-0.5 text-xs font-bold {badgeClass(tracking.confidence, tracking.stale)}"
			>
				{labelText(tracking.confidence, tracking.stale)}
			</span>
			{#if tracking.line_num != null}
				<span class="text-xs text-gray-500">L{tracking.line_num}</span>
			{/if}
			{#if tracking.stale}
				<span class="text-xs text-gray-600">· 추적 정보 오래됨</span>
			{/if}
		</div>
		<p class="truncate text-sm text-gray-300" title={tracking.text}>
			{tracking.text}
		</p>
		{#if tracking.plan_file}
			<p class="mt-0.5 truncate text-xs text-gray-600" title={tracking.plan_file}>
				{tracking.plan_file.split('/').pop() ?? tracking.plan_file}
			</p>
		{/if}
	</div>
{/if}
