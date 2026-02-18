<script lang="ts">
	import type { AutoNextTaskResponse } from '$lib/api';

	interface Props {
		task: AutoNextTaskResponse | null;
	}

	let { task }: Props = $props();

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
		if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
		return String(n);
	}
</script>

{#if !task}
	<div class="flex items-center justify-center h-full text-sm text-gray-400 py-6">
		실행 중인 작업 없음
	</div>
{:else}
	<div class="flex flex-col gap-3">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-2">
				<div class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
				<span class="text-xs font-medium text-blue-600 uppercase tracking-wider">Active Task</span>
			</div>
			<span class="bg-blue-100 text-blue-600 border border-blue-200 text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded">
				{task.id.slice(0, 8)}
			</span>
		</div>

		<!-- Prompt -->
		<p class="text-sm leading-relaxed line-clamp-3">{task.text}</p>

		<!-- Meta info -->
		<div class="flex items-center gap-4 text-xs text-gray-500 flex-wrap">
			<span class="flex items-center gap-1.5">
				<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>
				<span class="font-mono">{task.model_used || 'unknown'}</span>
			</span>
			{#if task.source_path}
				<span class="flex items-center gap-1.5">
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
					<span class="truncate max-w-[160px]">{task.source_path.split(/[\\/]/).pop()}</span>
				</span>
			{/if}
			<span class="flex items-center gap-1.5">
				<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
				<span class="font-mono tabular-nums">Running...</span>
			</span>
		</div>

		<!-- Live token counter -->
		{#if task.input_tokens || task.output_tokens || task.cache_read_tokens}
			<div class="flex gap-3 text-xs">
				<div class="flex items-center gap-1.5 rounded bg-gray-50 px-2 py-1">
					<span class="text-gray-500">In:</span>
					<span class="font-mono tabular-nums">{formatTokens(task.input_tokens)}</span>
				</div>
				<div class="flex items-center gap-1.5 rounded bg-gray-50 px-2 py-1">
					<span class="text-gray-500">Out:</span>
					<span class="font-mono tabular-nums">{formatTokens(task.output_tokens)}</span>
				</div>
				<div class="flex items-center gap-1.5 rounded bg-gray-50 px-2 py-1">
					<span class="text-gray-500">Cached:</span>
					<span class="font-mono tabular-nums">{formatTokens(task.cache_read_tokens)}</span>
				</div>
			</div>
		{/if}
	</div>
{/if}
