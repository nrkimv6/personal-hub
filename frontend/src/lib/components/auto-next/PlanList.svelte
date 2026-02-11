<script lang="ts">
	import type { AutoNextPlanFileResponse } from '$lib/api';

	interface Props {
		plans: AutoNextPlanFileResponse[];
	}

	let { plans }: Props = $props();

	function statusBadge(status: string): string {
		const map: Record<string, string> = {
			'구현중': 'bg-blue-100 text-blue-700',
			'완료': 'bg-green-100 text-green-700',
			'계획': 'bg-gray-100 text-gray-700',
			'보류': 'bg-yellow-100 text-yellow-700'
		};
		return map[status] || 'bg-gray-100 text-gray-700';
	}
</script>

<div class="bg-white rounded-lg border p-4">
	<h2 class="font-semibold mb-3">Plan 목록</h2>

	{#if plans.length === 0}
		<p class="text-gray-400 text-sm">Plan 파일이 없습니다</p>
	{:else}
		<div class="space-y-2">
			{#each plans as plan}
				<div class="border rounded-lg p-3 hover:bg-gray-50 transition-colors">
					<div class="flex items-center justify-between mb-1">
						<span class="text-sm font-medium truncate" title={plan.filename}>{plan.filename}</span>
						<span class="inline-block px-2 py-0.5 rounded text-xs font-medium {statusBadge(plan.status)}">
							{plan.status}
						</span>
					</div>
					<div class="flex items-center gap-2">
						<div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
							<div
								class="h-full rounded-full transition-all {plan.progress.percent >= 100 ? 'bg-green-500' : 'bg-blue-500'}"
								style="width: {plan.progress.percent}%"
							></div>
						</div>
						<span class="text-xs text-gray-500 whitespace-nowrap">
							{plan.progress.done}/{plan.progress.total} ({plan.progress.percent}%)
						</span>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
