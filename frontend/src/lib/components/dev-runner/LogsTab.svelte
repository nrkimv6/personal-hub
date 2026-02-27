<script lang="ts">
	import { devRunnerLogApi, type RunHistoryItem } from '$lib/api';
	import RunHistoryPanel from './RunHistoryPanel.svelte';
	import LogViewer from './LogViewer.svelte';

	// ── 상태 ──────────────────────────────────────────────────
	let selectedRunner = $state<RunHistoryItem | null>(null);
	let selectedRunnerId = $state<string | null>(null);

	// 시스템 로그 토글
	let showSystemLog = $state(false);
	let systemLines = $state<string[]>([]);
	let systemLoading = $state(false);
	let systemError = $state<string | null>(null);

	// ── 핸들러 ──────────────────────────────────────────────
	function handleSelect(item: RunHistoryItem) {
		selectedRunner = item;
		selectedRunnerId = item.runner_id;
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
</script>

<div class="flex flex-col h-full overflow-hidden">
	<!-- 메인 패널: 이력 목록 + 로그 뷰어 -->
	<div class="flex flex-1 min-h-0 overflow-hidden">
		<!-- 왼쪽: 실행 이력 패널 -->
		<RunHistoryPanel bind:selectedRunnerId onSelect={handleSelect} />

		<!-- 오른쪽: 로그 뷰어 -->
		<div class="flex-1 min-w-0 overflow-hidden">
			{#if selectedRunner}
				<LogViewer
					runnerId={selectedRunner.runner_id}
					planFile={selectedRunner.plan_file ?? undefined}
				/>
			{:else}
				<div class="flex items-center justify-center h-full text-gray-600 text-sm">
					<div class="text-center">
						<div class="text-4xl mb-3">📋</div>
						<div>왼쪽 목록에서 실행 이력을 선택하세요</div>
					</div>
				</div>
			{/if}
		</div>
	</div>

	<!-- 하단: Listener 시스템 로그 토글 -->
	<div class="border-t border-gray-700 flex-shrink-0">
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
