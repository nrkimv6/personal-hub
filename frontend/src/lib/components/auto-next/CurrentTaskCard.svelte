<script lang="ts">
	import type { TaskResponse } from '$lib/api';

	interface Props {
		task: TaskResponse | null;
		onShowDetail: () => void;
	}

	let { task, onShowDetail }: Props = $props();
	let showDetail = $state(false);

	function toggleDetail() {
		showDetail = !showDetail;
		if (showDetail) {
			onShowDetail();
		}
	}
</script>

{#if task}
	<div class="bg-blue-50 border border-blue-200 rounded-lg p-4">
		<div class="flex items-center justify-between mb-2">
			<div class="flex items-center gap-2">
				<div class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
				<span class="font-medium text-blue-900">현재 작업</span>
			</div>
			<span class="text-xs text-blue-600 font-medium px-2 py-1 bg-blue-100 rounded">
				{task.model_used || 'unknown'}
			</span>
		</div>
		<p class="text-sm text-blue-800 mb-3">{task.text}</p>
		<button
			onclick={toggleDetail}
			class="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors"
		>
			{showDetail ? '간략히 보기 ▴' : '상세 보기 ▾'}
		</button>
	</div>
{/if}
