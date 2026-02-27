<script lang="ts">
	import { onMount } from 'svelte';
	import { devRunnerLogApi, type RunHistoryItem, type FullLogResponse } from '$lib/api';

	// ── 상태 ──────────────────────────────────────────────────
	let runs = $state<RunHistoryItem[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	interface RunWithLogs {
		run: RunHistoryItem;
		lines: string[];
		logLoading: boolean;
		logError: string | null;
	}
	let runsWithLogs = $state<RunWithLogs[]>([]);

	// 시스템 로그 토글
	let showSystemLog = $state(false);
	let systemLines = $state<string[]>([]);
	let systemLoading = $state(false);
	let systemError = $state<string | null>(null);

	// ── 데이터 로드 ──────────────────────────────────────────
	async function loadAll() {
		loading = true;
		error = null;
		try {
			const res = await devRunnerLogApi.history(10, 0);
			runs = res.runs;
			runsWithLogs = runs.map((run) => ({
				run,
				lines: [],
				logLoading: false,
				logError: null,
			}));

			// 각 run의 로그를 순서대로 fetch
			for (let i = 0; i < runsWithLogs.length; i++) {
				const item = runsWithLogs[i];
				if (!item.run.has_log) continue;
				item.logLoading = true;
				try {
					const logRes = await devRunnerLogApi.full(item.run.runner_id, 0, 500);
					item.lines = logRes.lines;
				} catch (e) {
					item.logError = String(e);
				} finally {
					item.logLoading = false;
				}
				runsWithLogs = [...runsWithLogs]; // 반응성 트리거
			}
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	}

	async function toggleSystemLog() {
		showSystemLog = !showSystemLog;
		if (showSystemLog && systemLines.length === 0) {
			await loadSystemLog();
		}
	}

	async function loadSystemLog() {
		systemLoading = true;
		systemError = null;
		try {
			const res = await devRunnerLogApi.system(200);
			systemLines = res.lines;
		} catch (e) {
			systemError = String(e);
		} finally {
			systemLoading = false;
		}
	}

	function formatTime(iso: string | null): string {
		if (!iso) return '';
		try {
			return new Date(iso).toLocaleString('ko-KR', {
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			});
		} catch {
			return iso;
		}
	}

	onMount(() => {
		loadAll();
	});
</script>

<div class="flex flex-col h-full overflow-hidden bg-gray-950 text-gray-200">
	<!-- 헤더: 타이틀 + 새로고침 -->
	<div class="flex items-center gap-2 px-3 py-2 border-b border-gray-800 shrink-0">
		<span class="text-xs font-semibold text-gray-300 uppercase tracking-wider">📋 통합 실행 로그</span>
		<span class="text-[10px] text-gray-500 ml-1">최근 10개 실행</span>
		<button
			onclick={loadAll}
			class="ml-auto text-[10px] text-gray-500 hover:text-gray-300 transition-colors px-2 py-0.5 rounded border border-gray-700 hover:border-gray-500"
			title="새로고침"
		>
			↺ 새로고침
		</button>
	</div>

	<!-- 로그 본문 -->
	<div class="flex-1 min-h-0 overflow-y-auto">
		{#if loading}
			<div class="flex items-center justify-center h-32 text-gray-500 text-sm">로딩 중…</div>
		{:else if error}
			<div class="p-4 text-xs text-red-400">{error}</div>
		{:else if runsWithLogs.length === 0}
			<div class="flex items-center justify-center h-32 text-gray-600 text-sm">
				실행 이력이 없습니다
			</div>
		{:else}
			{#each runsWithLogs as item, idx (item.run.runner_id)}
				<!-- 세션 구분선 (최신 = idx 0은 정상 색상, 이전은 grayout) -->
				<div class="sticky top-0 z-10 flex items-center gap-2 px-3 py-1.5 border-b {idx === 0 ? 'bg-gray-900 border-gray-700' : 'bg-gray-950 border-gray-800'}">
					<!-- 상태 배지 -->
					<span class="text-[10px] font-mono {idx === 0 ? 'text-blue-400' : 'text-gray-600'}">
						{item.run.status === 'running' ? '⏳' : item.run.status === 'completed' ? '✅' : '❓'}
					</span>
					<!-- plan 파일명 -->
					<span class="text-[11px] font-mono font-semibold {idx === 0 ? 'text-gray-200' : 'text-gray-500'}">
						{item.run.plan_file ? item.run.plan_file.split(/[\\/]/).pop() : '전체 실행'}
					</span>
					<!-- 시간 -->
					{#if item.run.start_time}
						<span class="text-[10px] {idx === 0 ? 'text-gray-400' : 'text-gray-600'} ml-1">
							{formatTime(item.run.start_time)}
							{#if item.run.end_time} → {formatTime(item.run.end_time)}{/if}
						</span>
					{/if}
					<!-- runner id (짧게) -->
					<span class="ml-auto text-[9px] font-mono {idx === 0 ? 'text-gray-600' : 'text-gray-700'}">
						{item.run.runner_id.slice(0, 8)}
					</span>
				</div>

				<!-- 로그 라인들 -->
				<div class="px-3 pb-3 {idx === 0 ? '' : 'opacity-50'}">
					{#if item.logLoading}
						<div class="py-2 text-[11px] text-gray-600">로그 로딩 중…</div>
					{:else if item.logError}
						<div class="py-2 text-[11px] text-red-500">{item.logError}</div>
					{:else if !item.run.has_log}
						<div class="py-2 text-[11px] text-gray-700">로그 없음</div>
					{:else if item.lines.length === 0}
						<div class="py-2 text-[11px] text-gray-700">빈 로그</div>
					{:else}
						{#each item.lines as line, li (li)}
							<div class="font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all {idx === 0 ? 'text-gray-300' : 'text-gray-500'}">
								{line}
							</div>
						{/each}
					{/if}
				</div>
			{/each}
		{/if}
	</div>

	<!-- 하단: Listener 시스템 로그 토글 -->
	<div class="border-t border-gray-700 shrink-0">
		<button
			onclick={toggleSystemLog}
			class="w-full flex items-center gap-2 px-4 py-2 text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
		>
			<svg
				class="w-3.5 h-3.5 transition-transform {showSystemLog ? 'rotate-180' : ''}"
				fill="none" stroke="currentColor" viewBox="0 0 24 24"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
			<span class="font-medium">시스템 로그 (Listener)</span>
			{#if systemLines.length > 0}
				<span class="ml-auto text-gray-600">{systemLines.length}줄</span>
			{/if}
		</button>

		{#if showSystemLog}
			<div class="bg-gray-950 border-t border-gray-800 max-h-48 overflow-y-auto">
				{#if systemLoading}
					<div class="p-3 text-xs text-gray-500">로딩 중…</div>
				{:else if systemError}
					<div class="p-3 text-xs text-red-400">{systemError}</div>
				{:else if systemLines.length === 0}
					<div class="p-3 text-xs text-gray-600">시스템 로그 없음</div>
				{:else}
					<div class="p-2">
						{#each systemLines as line, i (i)}
							<div class="font-mono text-[11px] text-gray-400 leading-relaxed whitespace-pre-wrap break-all">
								{line}
							</div>
						{/each}
					</div>
				{/if}
				<!-- 새로고침 버튼 -->
				<div class="sticky bottom-0 bg-gray-950 border-t border-gray-800 px-3 py-1.5 flex justify-end">
					<button
						onclick={loadSystemLog}
						class="text-[10px] text-gray-500 hover:text-gray-300 transition-colors"
					>
						새로고침
					</button>
				</div>
			</div>
		{/if}
	</div>
</div>
