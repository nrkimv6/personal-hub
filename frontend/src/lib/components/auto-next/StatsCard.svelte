<script lang="ts">
	import type { AutoNextStatsResponse } from '$lib/api';

	interface Props {
		stats: AutoNextStatsResponse;
		currentRunStats: AutoNextStatsResponse | null;
		isRunning: boolean;
	}

	let { stats, currentRunStats, isRunning }: Props = $props();

	let showCurrent = $state(true);

	const emptyStats: AutoNextStatsResponse = {
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
		if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
		return String(n);
	}

	function formatDuration(ms: number): string {
		const minutes = Math.floor(ms / 60000);
		if (minutes >= 60) {
			const hours = Math.floor(minutes / 60);
			const mins = minutes % 60;
			return `${hours}h ${mins}m`;
		}
		return `${minutes}m`;
	}

	let segs = $derived.by(() => {
		const total = displayStats.total || 1;
		return {
			success: (displayStats.success / total) * 100,
			failed: (displayStats.failed / total) * 100,
			running: (displayStats.running / total) * 100,
			pending: (displayStats.pending / total) * 100,
			skipped: (displayStats.skipped / total) * 100
		};
	});
</script>

<!-- 탭 전환 -->
<div class="flex items-center gap-2 mb-3">
	<div class="flex rounded-lg border text-xs overflow-hidden">
		<button
			class="px-2.5 py-1 transition-colors {showCurrent ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
			onclick={() => (showCurrent = true)}
		>
			{isRunning ? '현재 실행' : '마지막 실행'}
		</button>
		<button
			class="px-2.5 py-1 transition-colors {!showCurrent ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
			onclick={() => (showCurrent = false)}
		>
			전체 누적
		</button>
	</div>
	{#if showCurrent && !currentRunStats}
		<span class="text-xs text-gray-400">실행 기록 없음</span>
	{/if}
</div>

<!-- Phase 3: 3-column 큰 숫자 요약 -->
<div class="grid grid-cols-3 gap-4 mb-4">
	<div class="bg-white rounded-lg border p-4 text-center">
		<div class="text-3xl font-bold mt-1">{displayStats.total}</div>
		<div class="text-xs text-gray-500 mt-1">전체 작업</div>
		<div class="text-xs text-gray-400 mt-0.5">완료 {displayStats.completed}</div>
	</div>
	<div class="bg-white rounded-lg border p-4 text-center">
		<div class="text-3xl font-bold mt-1">{displayStats.completion_rate.toFixed(1)}%</div>
		<div class="text-xs text-gray-500 mt-1">완료율</div>
		<div class="text-xs text-gray-400 mt-0.5">대기 {displayStats.pending}</div>
	</div>
	<div class="bg-white rounded-lg border p-4 text-center">
		<div class="text-3xl font-bold mt-1">{displayStats.success_rate.toFixed(1)}%</div>
		<div class="text-xs text-gray-500 mt-1">성공률</div>
		<div class="text-xs text-gray-400 mt-0.5">성공 {displayStats.success} / 실패 {displayStats.failed}</div>
	</div>
</div>

<!-- Phase 3: Progress Bar (순서 변경: 3-column 요약 바로 아래) -->
<div class="bg-white rounded-lg border p-4 mb-4">
	<div class="flex items-center justify-between text-sm text-gray-500 mb-2">
		<span>진행 상황</span>
		<span>{displayStats.completion_rate.toFixed(1)}% 완료</span>
	</div>
	<div class="w-full h-3 bg-gray-100 rounded-full overflow-hidden flex">
		{#if segs.success > 0}
			<div class="bg-green-500 h-full" style="width: {segs.success}%"></div>
		{/if}
		{#if segs.failed > 0}
			<div class="bg-red-500 h-full" style="width: {segs.failed}%"></div>
		{/if}
		{#if segs.skipped > 0}
			<div class="bg-yellow-400 h-full" style="width: {segs.skipped}%"></div>
		{/if}
		{#if segs.running > 0}
			<div class="bg-blue-500 h-full animate-pulse" style="width: {segs.running}%"></div>
		{/if}
		{#if segs.pending > 0}
			<div class="bg-gray-300 h-full" style="width: {segs.pending}%"></div>
		{/if}
	</div>
	<div class="flex gap-4 mt-2 text-xs text-gray-500 flex-wrap">
		<span class="flex items-center gap-1"
			><span class="w-2 h-2 rounded-full bg-green-500 inline-block"></span> 성공 {displayStats.success}</span
		>
		<span class="flex items-center gap-1"
			><span class="w-2 h-2 rounded-full bg-red-500 inline-block"></span> 실패 {displayStats.failed}</span
		>
		<span class="flex items-center gap-1"
			><span class="w-2 h-2 rounded-full bg-yellow-400 inline-block"></span> 스킵 {displayStats.skipped}</span
		>
		<span class="flex items-center gap-1"
			><span class="w-2 h-2 rounded-full bg-blue-500 inline-block"></span> 실행 중 {displayStats.running}</span
		>
		<span class="flex items-center gap-1"
			><span class="w-2 h-2 rounded-full bg-gray-300 inline-block"></span> 대기 {displayStats.pending}</span
		>
	</div>
</div>

<!-- Phase 3: 2x2 토큰 그리드 박스 (Progress Bar 아래) -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-2">
	<div class="bg-gray-50 rounded p-2 text-center">
		<div class="text-xs text-gray-500">Tokens In</div>
		<div class="text-sm font-semibold mt-0.5">{formatTokens(displayStats.total_input_tokens)}</div>
	</div>
	<div class="bg-gray-50 rounded p-2 text-center">
		<div class="text-xs text-gray-500">Tokens Out</div>
		<div class="text-sm font-semibold mt-0.5">{formatTokens(displayStats.total_output_tokens)}</div>
	</div>
	<div class="bg-gray-50 rounded p-2 text-center">
		<div class="text-xs text-gray-500">Cached</div>
		<div class="text-sm font-semibold mt-0.5">{formatTokens(displayStats.total_cache_tokens)}</div>
	</div>
	<div class="bg-gray-50 rounded p-2 text-center">
		<div class="text-xs text-gray-500">Duration</div>
		<div class="text-sm font-semibold mt-0.5">{formatDuration(displayStats.total_duration_ms)}</div>
	</div>
</div>
