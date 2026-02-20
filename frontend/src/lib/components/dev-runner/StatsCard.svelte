<script lang="ts">
	import type { DevRunnerStatsResponse } from '$lib/api';

	interface Props {
		stats: DevRunnerStatsResponse;
		currentRunStats: DevRunnerStatsResponse | null;
		isRunning: boolean;
	}

	let { stats, currentRunStats, isRunning }: Props = $props();

	let showCurrent = $state(true);

	const emptyStats: DevRunnerStatsResponse = {
		total: 0, pending: 0, running: 0, success: 0, failed: 0, skipped: 0,
		completed: 0, completion_rate: 0, success_rate: 0,
		total_input_tokens: 0, total_output_tokens: 0, total_cache_tokens: 0,
		total_tokens: 0, total_duration_ms: 0
	};

	let displayStats = $derived(
		showCurrent ? (currentRunStats ?? emptyStats) : stats
	);

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
		if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k';
		return String(n);
	}

	function formatDuration(ms: number): string {
		const seconds = Math.floor(ms / 1000);
		if (seconds >= 3600) {
			const h = Math.floor(seconds / 3600);
			const m = Math.floor((seconds % 3600) / 60);
			return `${h}h ${m}m`;
		}
		if (seconds >= 60) {
			const m = Math.floor(seconds / 60);
			const s = seconds % 60;
			return `${m}m ${s}s`;
		}
		return `${seconds}s`;
	}

	let segs = $derived.by(() => {
		const total = displayStats.total || 1;
		return [
			{ value: displayStats.success, pct: (displayStats.success / total) * 100, color: 'bg-green-500', label: '성공' },
			{ value: displayStats.running, pct: (displayStats.running / total) * 100, color: 'bg-blue-500', label: '실행 중' },
			{ value: displayStats.failed, pct: (displayStats.failed / total) * 100, color: 'bg-red-500', label: '실패' },
			{ value: displayStats.skipped, pct: (displayStats.skipped / total) * 100, color: 'bg-gray-400', label: '스킵' },
			{ value: displayStats.pending, pct: (displayStats.pending / total) * 100, color: 'bg-gray-200', label: '대기' }
		];
	});
</script>

<!-- Tabs -->
<div class="flex flex-col gap-3">
	<div class="flex rounded-lg border text-xs overflow-hidden w-full">
		<button
			class="flex-1 px-2.5 py-1 transition-colors {showCurrent ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'}"
			onclick={() => (showCurrent = true)}
		>
			{isRunning ? '현재 실행' : '마지막 실행'}
		</button>
		<button
			class="flex-1 px-2.5 py-1 transition-colors {!showCurrent ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'}"
			onclick={() => (showCurrent = false)}
		>
			전체 누적
		</button>
	</div>

	{#if showCurrent && !currentRunStats}
		<span class="text-xs text-gray-400">실행 기록 없음</span>
	{/if}

	<!-- 3-col big numbers -->
	<div class="grid grid-cols-3 gap-3">
		<div class="flex flex-col gap-0.5">
			<span class="text-2xl font-semibold tabular-nums">{displayStats.total}</span>
			<span class="text-xs text-gray-500">전체 작업</span>
		</div>
		<div class="flex flex-col gap-0.5">
			<span class="text-2xl font-semibold text-green-600 tabular-nums">{displayStats.completion_rate.toFixed(0)}%</span>
			<span class="text-xs text-gray-500">완료율</span>
		</div>
		<div class="flex flex-col gap-0.5">
			<span class="text-2xl font-semibold text-blue-600 tabular-nums">{displayStats.success_rate.toFixed(0)}%</span>
			<span class="text-xs text-gray-500">성공률</span>
		</div>
	</div>

	<!-- Progress Bar -->
	<div class="flex flex-col gap-2">
		<div class="flex h-2 w-full overflow-hidden rounded-full bg-gray-100">
			{#each segs as seg}
				{#if seg.value > 0}
					<div
						class="{seg.color} transition-all duration-500 {seg.label === '실행 중' ? 'animate-pulse' : ''}"
						style="width: {seg.pct}%"
					></div>
				{/if}
			{/each}
		</div>
		<div class="flex flex-wrap gap-x-3 gap-y-1">
			{#each segs as seg}
				{#if seg.value > 0}
					<div class="flex items-center gap-1.5 text-xs text-gray-500">
						<div class="w-2 h-2 rounded-full {seg.color}"></div>
						<span>{seg.label} {seg.value}</span>
					</div>
				{/if}
			{/each}
		</div>
	</div>

	<!-- Token Usage 2x2 -->
	<div class="grid grid-cols-2 gap-3">
		<div class="flex flex-col gap-1 rounded-md bg-gray-50 p-2.5">
			<span class="text-xs text-gray-500">Tokens In</span>
			<span class="text-sm font-mono font-medium">{formatTokens(displayStats.total_input_tokens)}</span>
		</div>
		<div class="flex flex-col gap-1 rounded-md bg-gray-50 p-2.5">
			<span class="text-xs text-gray-500">Tokens Out</span>
			<span class="text-sm font-mono font-medium">{formatTokens(displayStats.total_output_tokens)}</span>
		</div>
		<div class="flex flex-col gap-1 rounded-md bg-gray-50 p-2.5">
			<span class="text-xs text-gray-500">Cached</span>
			<span class="text-sm font-mono font-medium">{formatTokens(displayStats.total_cache_tokens)}</span>
		</div>
		<div class="flex flex-col gap-1 rounded-md bg-gray-50 p-2.5">
			<span class="text-xs text-gray-500">Duration</span>
			<span class="text-sm font-mono font-medium">{formatDuration(displayStats.total_duration_ms)}</span>
		</div>
	</div>
</div>
