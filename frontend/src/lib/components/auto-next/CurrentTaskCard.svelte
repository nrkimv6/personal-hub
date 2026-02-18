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
		<p class="text-sm text-blue-800 mb-2">{task.text}</p>
		<button
			onclick={toggleDetail}
			class="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors mb-2"
		>
			{showDetail ? '간략히 보기 ▴' : '상세 보기 ▾'}
		</button>
		<!-- Phase 3: 토큰 인라인 뱃지 -->
		{#if (task.input_tokens || task.output_tokens || task.cache_read_tokens)}
			<div class="flex items-center gap-2 text-xs mt-1">
				{#if task.input_tokens}
					<span class="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">In: {task.input_tokens.toLocaleString()}</span>
				{/if}
				{#if task.output_tokens}
					<span class="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Out: {task.output_tokens.toLocaleString()}</span>
				{/if}
				{#if task.cache_read_tokens}
					<span class="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">Cache: {task.cache_read_tokens.toLocaleString()}</span>
				{/if}
			</div>
		{/if}
	</div>
{/if}
