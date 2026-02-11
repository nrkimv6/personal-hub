<script lang="ts">
	import type { AutoNextStatsResponse } from '$lib/api';

	interface Props {
		stats: AutoNextStatsResponse;
	}

	let { stats }: Props = $props();

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

	let progressSegments = $derived(() => {
		const total = stats.total || 1;
		return {
			success: (stats.success / total) * 100,
			failed: (stats.failed / total) * 100,
			running: (stats.running / total) * 100,
			pending: (stats.pending / total) * 100,
			skipped: (stats.skipped / total) * 100
		};
	});
</script>

<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
	<div class="bg-white rounded-lg border p-4">
		<div class="text-sm text-gray-500">전체 작업</div>
		<div class="text-2xl font-bold mt-1">{stats.total}</div>
		<div class="text-xs text-gray-400 mt-1">완료 {stats.completed}</div>
	</div>
	<div class="bg-white rounded-lg border p-4">
		<div class="text-sm text-gray-500">성공률</div>
		<div class="text-2xl font-bold mt-1">{stats.success_rate.toFixed(1)}%</div>
		<div class="text-xs text-gray-400 mt-1">성공 {stats.success} / 실패 {stats.failed}</div>
	</div>
	<div class="bg-white rounded-lg border p-4">
		<div class="text-sm text-gray-500">총 토큰</div>
		<div class="text-2xl font-bold mt-1">{formatTokens(stats.total_tokens)}</div>
		<div class="text-xs text-gray-400 mt-1">입력 {formatTokens(stats.total_input_tokens)} / 출력 {formatTokens(stats.total_output_tokens)}</div>
	</div>
	<div class="bg-white rounded-lg border p-4">
		<div class="text-sm text-gray-500">총 실행시간</div>
		<div class="text-2xl font-bold mt-1">{formatDuration(stats.total_duration_ms)}</div>
		<div class="text-xs text-gray-400 mt-1">캐시 {formatTokens(stats.total_cache_tokens)}</div>
	</div>
</div>

<!-- Progress Bar -->
<div class="mt-4 bg-white rounded-lg border p-4">
	<div class="flex items-center justify-between text-sm text-gray-500 mb-2">
		<span>진행 상황</span>
		<span>{stats.completion_rate.toFixed(1)}% 완료</span>
	</div>
	<div class="w-full h-3 bg-gray-100 rounded-full overflow-hidden flex">
		{@const segs = progressSegments()}
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
		<span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-green-500 inline-block"></span> 성공 {stats.success}</span>
		<span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-red-500 inline-block"></span> 실패 {stats.failed}</span>
		<span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-yellow-400 inline-block"></span> 스킵 {stats.skipped}</span>
		<span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-blue-500 inline-block"></span> 실행 중 {stats.running}</span>
		<span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-gray-300 inline-block"></span> 대기 {stats.pending}</span>
	</div>
</div>
