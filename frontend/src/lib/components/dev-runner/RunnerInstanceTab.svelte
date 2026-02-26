<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerRunnerApi } from '$lib/api';
	import type { DevRunnerRunStatusResponse } from '$lib/api';
	import LogViewer from './LogViewer.svelte';

	interface Props {
		runnerId: string;
		planFile: string | null;
		running: boolean;
		engine: string | null;
		startTime: string | null;
		worktreePath?: string | null;
		branch?: string | null;
		mergeStatus?: string | null;
		onStop: () => void;
		onClose: () => void;
	}

	let { runnerId, planFile, running, engine, startTime, worktreePath = null, branch = null, mergeStatus = null, onStop, onClose }: Props = $props();

	let elapsed = $state('');
	let stopping = $state(false);
	let stopError = $state<string | null>(null);
	let retryingMerge = $state(false);
	let mergeError = $state<string | null>(null);
	let intervalId: ReturnType<typeof setInterval> | null = null;

	function formatElapsed(startIso: string | null): string {
		if (!startIso) return '';
		const startMs = new Date(startIso).getTime();
		const diffSec = Math.floor((Date.now() - startMs) / 1000);
		if (diffSec < 60) return `${diffSec}s`;
		const m = Math.floor(diffSec / 60);
		const s = diffSec % 60;
		if (m < 60) return `${m}m ${s}s`;
		const h = Math.floor(m / 60);
		return `${h}h ${m % 60}m`;
	}

	onMount(() => {
		elapsed = formatElapsed(startTime);
		intervalId = setInterval(() => {
			elapsed = formatElapsed(startTime);
		}, 1000);
	});

	onDestroy(() => {
		if (intervalId) clearInterval(intervalId);
	});

	async function handleStop() {
		if (!confirm('이 runner를 중지하시겠습니까?')) return;
		stopping = true;
		stopError = null;
		try {
			await devRunnerRunnerApi.stop(runnerId);
			onStop();
		} catch (e) {
			stopError = e instanceof Error ? e.message : '중지 실패';
		} finally {
			stopping = false;
		}
	}

	async function handleRetryMerge() {
		retryingMerge = true;
		mergeError = null;
		try {
			await devRunnerRunnerApi.retryMerge(runnerId);
		} catch (e) {
			mergeError = e instanceof Error ? e.message : '머지 재시도 실패';
		} finally {
			retryingMerge = false;
		}
	}

	async function handleCleanupWorktree() {
		if (!confirm('worktree를 정리하시겠습니까? 미저장 변경사항이 삭제됩니다.')) return;
		try {
			await devRunnerRunnerApi.cleanupWorktree(runnerId);
		} catch (e) {
			mergeError = e instanceof Error ? e.message : 'worktree 정리 실패';
		}
	}

	let planBasename = $derived(
		planFile ? planFile.split(/[\\/]/).pop() ?? planFile : '전체 실행'
	);

	let statusIcon = $derived(running ? '⏳' : '✅');
</script>

<div class="flex flex-col h-full">
	<!-- 헤더 바 -->
	<div class="flex items-center gap-2 px-3 py-1.5 bg-gray-50 border-b border-gray-200 text-xs shrink-0">
		<span class="text-base leading-none">{statusIcon}</span>

		<span class="font-mono font-medium text-gray-700 truncate max-w-[160px]" title={planFile ?? '전체 실행'}>
			{planBasename}
		</span>

		{#if engine}
			<span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase {engine === 'gemini' ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700'}">
				{engine}
			</span>
		{/if}

		<span class="text-gray-400 font-mono text-[10px]">{runnerId}</span>

		{#if branch}
			<span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-100 text-purple-700" title={worktreePath ?? branch}>
				{branch}
			</span>
		{/if}

		{#if mergeStatus === 'merged'}
			<span class="px-1.5 py-0.5 rounded text-[10px] bg-green-100 text-green-700">머지됨</span>
		{:else if mergeStatus === 'conflict'}
			<span class="px-1.5 py-0.5 rounded text-[10px] bg-red-100 text-red-700">충돌</span>
		{/if}

		{#if elapsed}
			<span class="text-gray-400 text-[10px] ml-auto shrink-0">{elapsed}</span>
		{/if}

		{#if running}
			<button
				class="shrink-0 px-2 py-0.5 rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors text-[10px]"
				onclick={handleStop}
				disabled={stopping}
			>
				{stopping ? '중지 중...' : '중지'}
			</button>
		{/if}

		<button
			class="shrink-0 w-5 h-5 flex items-center justify-center rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 transition-colors"
			onclick={onClose}
			title="탭 닫기"
		>
			×
		</button>
	</div>

	{#if stopError}
		<div class="px-3 py-1 text-xs text-red-600 bg-red-50 border-b border-red-100">{stopError}</div>
	{/if}

	{#if mergeStatus === 'conflict'}
		<div class="flex items-center gap-2 px-3 py-2 bg-red-50 border-b border-red-200 text-xs">
			<span class="text-red-700 font-medium">머지 충돌이 발생했습니다.</span>
			<button
				class="px-2 py-0.5 rounded border border-red-300 text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors"
				onclick={handleRetryMerge}
				disabled={retryingMerge}
			>
				{retryingMerge ? '재시도 중...' : '머지 재시도'}
			</button>
			<button
				class="px-2 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 transition-colors"
				onclick={handleCleanupWorktree}
			>
				Worktree 정리
			</button>
		</div>
	{/if}

	{#if mergeError}
		<div class="px-3 py-1 text-xs text-red-600 bg-red-50 border-b border-red-100">{mergeError}</div>
	{/if}

	<!-- 로그 뷰어 -->
	<div class="flex-1 min-h-0">
		<LogViewer {runnerId} planFile={planFile ?? undefined} />
	</div>
</div>
