<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerRunnerApi, devRunnerWorkflowApi } from '$lib/api';
	import type { DevRunnerRunStatusResponse, GateEvidenceSummary } from '$lib/api';
	import LogViewer from './LogViewer.svelte';
	import { getExitReasonDisplay } from '$lib/utils/dev-runner-exit-reason';
	import { confirm } from '$lib/stores/confirm';

	interface LogViewerRef {
		injectLine: (text: string | { text: string; meta?: Record<string, unknown> }) => void;
		injectCompleted: (reason?: string) => void;
		injectMergeCompleted: (reason?: string, status?: string) => void;
		catchUp?: () => Promise<void>;
	}

	interface Props {
		runnerId: string;
		planFile: string | null;
		running: boolean;
		engine: string | null;
		startTime: string | null;
		worktreePath?: string | null;
		branch?: string | null;
		mergeStatus?: string | null;
		mergeReason?: string | null;
		mergeMessage?: string | null;
		trigger?: string | null;
		orphan?: boolean;
		orphanAlive?: boolean;
		redisMissing?: boolean;
		logFileFound?: boolean;
		exitReason?: string | null;
		error?: string | null;
		displayPlanName?: string | null;
		remainingPostMergeTasks?: number | null;
		mergeEvidenceMissing?: boolean | null;
		executionCount?: number | null;
		worktreeExists?: boolean | 'unknown';
		branchExists?: boolean | 'unknown';
		branchMergedToMain?: boolean | 'unknown';
		metadataCheckedAt?: string | null;
		displayLabel?: string | null;
		displaySecondary?: string | null;
		hideStaleBranchBadge?: boolean;
		gateEvidenceSummary?: GateEvidenceSummary | null;
		autoRetryBlocked?: boolean;
		reattachMode?: 'full' | 'log_only_child' | 'log_only';
		canReattach?: boolean;
		canForceKill?: boolean;
		orphanWarnings?: string[];
		onStop: () => void;
		onClose: () => void;
		onRestart?: () => void;
		onReattach?: () => void;
		onKillOrphan?: () => void;
		onBatchPlansChange?: (plans: { name: string; status: 'pending' | 'running' | 'done' }[]) => void;
		logRef?: (ref: LogViewerRef) => void;
	}

	let { runnerId, planFile, running, engine, startTime, worktreePath = null, branch = null, mergeStatus = null, mergeReason = null, mergeMessage = null, trigger = null, orphan = false, orphanAlive = false, redisMissing = false, logFileFound = false, exitReason = null, error = null, displayPlanName = null, remainingPostMergeTasks = null, mergeEvidenceMissing = null, executionCount = null, worktreeExists = 'unknown', branchExists = 'unknown', branchMergedToMain = 'unknown', metadataCheckedAt = 'unknown', displayLabel = null, displaySecondary = null, hideStaleBranchBadge = false, gateEvidenceSummary = null, autoRetryBlocked = false, reattachMode = 'log_only', canReattach = false, canForceKill = false, orphanWarnings = [], onStop, onClose, onRestart, onReattach, onKillOrphan, onBatchPlansChange, logRef }: Props = $props();

	let logViewer:
		| {
				injectLine: (t: string | { text: string; meta?: Record<string, unknown> }) => void;
				injectCompleted: (reason?: string) => void;
				injectMergeCompleted: (reason?: string, status?: string) => void;
				catchUp?: () => Promise<void>;
		  }
		| undefined;
	let elapsed = $state('');
	let stopping = $state(false);
	let killing = $state(false);
	let stopError = $state<string | null>(null);
	let retryingMerge = $state(false);
	let resolvingConflict = $state(false);
	let directMerging = $state(false);
	let mergeError = $state<string | null>(null);
	let intervalId: ReturnType<typeof setInterval> | null = null;

	async function handleOrphanReset() {
		try {
			const workflows = await devRunnerWorkflowApi.list({ status: 'running' });
			const wf = workflows.find(w => w.runner_id === runnerId);
			if (wf) {
				await devRunnerWorkflowApi.reset(wf.id);
			} else {
				// merge_pending도 확인
				const mpWorkflows = await devRunnerWorkflowApi.list({ status: 'merge_pending' });
				const mpWf = mpWorkflows.find(w => w.runner_id === runnerId);
				if (mpWf) await devRunnerWorkflowApi.reset(mpWf.id);
			}
			onClose();
		} catch (e) {
			mergeError = e instanceof Error ? e.message : '고아 리셋 실패';
		}
	}

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
		if (logViewer && logRef) {
			logRef({ injectLine: logViewer.injectLine, injectCompleted: logViewer.injectCompleted, injectMergeCompleted: logViewer.injectMergeCompleted, catchUp: logViewer.catchUp });
			void logViewer.catchUp?.();
		}
	});

	onDestroy(() => {
		if (intervalId) clearInterval(intervalId);
	});

	async function handleStop() {
		if (!await confirm({ title: 'Runner 중지', message: '이 runner를 중지하시겠습니까?', confirmText: '중지' })) return;
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

	async function handleKill() {
		if (!await confirm({
			title: 'Runner 강제 종료',
			message: `runner ${runnerId}를 강제 종료합니까? 진행 중인 작업이 유실됩니다.`,
			confirmText: '강제 종료',
			variant: 'danger'
		})) return;
		killing = true;
		stopError = null;
		try {
			await devRunnerRunnerApi.kill(runnerId);
			onStop();
		} catch (e) {
			stopError = e instanceof Error ? e.message : '강제 종료 실패';
		} finally {
			killing = false;
		}
	}

	async function handleRetryMerge() {
		retryingMerge = true;
		mergeError = null;
		try {
			await devRunnerRunnerApi.retryMerge(runnerId, {
				worktree_path: worktreePath ?? null,
				plan_file: planFile ?? null,
				branch: branch ?? null,
			});
		} catch (e) {
			mergeError = e instanceof Error ? e.message : '머지 재시도 실패';
		} finally {
			retryingMerge = false;
		}
	}

	async function handleApproveServiceLockAndRetryMerge() {
		retryingMerge = true;
		mergeError = null;
		try {
			await devRunnerRunnerApi.retryMerge(runnerId, {
				worktree_path: worktreePath ?? null,
				plan_file: planFile ?? null,
				branch: branch ?? null,
				approve_service_lock: true,
			});
		} catch (e) {
			mergeError = e instanceof Error ? e.message : '승인 후 머지 재시도 실패';
		} finally {
			retryingMerge = false;
		}
	}

	async function handleResolveConflict() {
		resolvingConflict = true;
		mergeError = null;
		try {
			await devRunnerRunnerApi.resolveConflict(runnerId);
		} catch (e) {
			mergeError = e instanceof Error ? e.message : '자동 해결 실패';
		} finally {
			resolvingConflict = false;
		}
	}

	async function handleDirectMerge() {
		if (!branch) return;
		directMerging = true;
		mergeError = null;
		try {
			await devRunnerRunnerApi.directMerge(branch, worktreePath ?? undefined);
		} catch (e) {
			mergeError = e instanceof Error ? e.message : '직접 머지 실패';
		} finally {
			directMerging = false;
		}
	}

	async function handleCleanupWorktree() {
		if (!await confirm({
			title: 'Worktree 정리',
			message: 'worktree를 정리하시겠습니까? 미저장 변경사항이 삭제됩니다.',
			confirmText: '정리',
			variant: 'danger'
		})) return;
		try {
			await devRunnerRunnerApi.cleanupWorktree(runnerId);
		} catch (e) {
			mergeError = e instanceof Error ? e.message : 'worktree 정리 실패';
		}
	}

	const isAllPlans = (f: string | null | undefined) =>
		f === '__ALL_PLANS__' || f === 'ALL';

	const ENGINE_LABELS: Record<string, string> = {
		claude: 'CLD',
		gemini: 'GEM',
		codex: 'COD',
		'cc-codex': 'CCX'
	};

	function getEngineLabel(value: string | null): string {
		if (!value) return '';
		return ENGINE_LABELS[value] ?? value.slice(0, 3).toUpperCase();
	}

	function getEngineClass(value: string | null): string {
		if (value === 'gemini') return 'bg-orange-100 text-orange-700 border-orange-200';
		if (value === 'codex') return 'bg-slate-100 text-slate-700 border-slate-300';
		if (value === 'cc-codex') return 'bg-emerald-100 text-emerald-700 border-emerald-200';
		return 'bg-green-100 text-green-700 border-green-200';
	}

	function staleBadgeLabel(): string | null {
		if (hideStaleBranchBadge) return null;
		return displaySecondary;
	}

	function gateEvidenceLabel(): string | null {
		if (!gateEvidenceSummary) return null;
		const reason = gateEvidenceSummary.reason;
		const status = gateEvidenceSummary.status;
		if (typeof reason === 'string' && reason) return reason;
		if (typeof status === 'string' && status) return status;
		return null;
	}

	function gateEvidenceTitle(): string {
		if (!gateEvidenceSummary) return '';
		return Object.entries(gateEvidenceSummary)
			.map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
			.join('\n');
	}

	let divergeEvidenceText = $derived.by(() => {
		if (!gateEvidenceSummary) return null;
		const d = gateEvidenceSummary.diverged_commits;
		const a = gateEvidenceSummary.already_in_main_commits;
		if (d == null && a == null) return null;
		const parts: string[] = [];
		if (typeof d === 'number' && d > 0) parts.push(`branch diverged ${d} commits`);
		if (typeof a === 'number' && a > 0) parts.push(`${a} commits already merged to main`);
		return parts.length > 0 ? parts.join(', ') : null;
	});

	let needsPostMergeFollowup = $derived(
		!running && (remainingPostMergeTasks ?? 0) > 0 && (exitReason === 'completed' || mergeEvidenceMissing === true)
	);

	let metaTitle = $derived.by(() => {
		const rows = [
			displayPlanName ? `plan: ${displayPlanName}` : null,
			planFile && !isAllPlans(planFile) ? `file: ${planFile}` : null,
			executionCount != null ? `run: ${executionCount}` : null,
			`runner: ${runnerId}`,
			engine ? `engine: ${engine}` : null,
			branch ? `branch: ${branch}` : null,
			worktreePath ? `worktree: ${worktreePath}` : null,
			`worktree_exists: ${worktreeExists}`,
			`branch_exists: ${branchExists}`,
			`branch_merged_to_main: ${branchMergedToMain}`,
			`orphan_alive: ${orphanAlive}`,
			`redis_missing: ${redisMissing}`,
			`log_file_found: ${logFileFound}`,
			`reattach_mode: ${reattachMode}`,
			`can_reattach: ${canReattach}`,
			`can_force_kill: ${canForceKill}`,
			orphanWarnings.length > 0 ? `warnings: ${orphanWarnings.join(', ')}` : null,
			`remaining_post_merge_tasks: ${remainingPostMergeTasks ?? 0}`,
			`merge_evidence_missing: ${mergeEvidenceMissing ?? false}`,
			`auto_retry_blocked: ${autoRetryBlocked}`,
			gateEvidenceLabel() ? `gate_evidence_summary: ${gateEvidenceLabel()}` : null,
			`metadata_checked_at: ${metadataCheckedAt ?? 'unknown'}`
		];
		return rows.filter(Boolean).join('\n');
	});

	let exitDisplay = $derived(getExitReasonDisplay(exitReason));
	function resolveHeaderStatus(runningValue: boolean, exitReasonValue: string | null, mergeStatusValue: string | null): string {
		if (displayLabel) return displayLabel;
		if (runningValue) return '실행중';
		if (mergeStatusValue === 'merged') return '머지됨';
		if (mergeStatusValue === 'test_failed') return '테스트 실패';
		if (mergeStatusValue === 'conflict') return '충돌';
		if (mergeStatusValue === 'error') return '머지 오류';
		return getExitReasonDisplay(exitReasonValue).statusIcon;
	}

	let statusIcon = $derived(resolveHeaderStatus(running, exitReason, mergeStatus));
</script>

<div class="flex flex-col h-full">
	<!-- 헤더 바 -->
	<div class="flex items-center gap-2 px-3 py-1.5 bg-muted/50 border-b border-border text-xs shrink-0" title={metaTitle}>
		<div class="flex min-w-0 flex-1 items-center gap-2">
			<span class="shrink-0 text-xs font-medium text-foreground">{statusIcon}</span>

			{#if engine}
				<span class="shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase {getEngineClass(engine)}" title={engine}>
					{getEngineLabel(engine)}
				</span>
			{/if}

			{#if mergeStatus === 'merged'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-green-100 text-green-700">머지됨</span>
			{:else if mergeStatus === 'merge_pending'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-blue-100 text-blue-700 animate-pulse">머지 대기</span>
			{:else if mergeStatus === 'merging' || mergeStatus === 'testing'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-blue-100 text-blue-700 animate-pulse">머지 중</span>
			{:else if mergeStatus === 'conflict'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-red-100 text-red-700">충돌</span>
			{:else if mergeStatus === 'test_failed'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-orange-100 text-orange-700">테스트 실패</span>
			{:else if mergeStatus === 'error'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-red-100 text-red-700">머지 오류</span>
			{:else if mergeStatus === 'fixing'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-yellow-100 text-yellow-700 animate-pulse">자동 수정 중</span>
			{:else if mergeStatus === 'resolving'}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-yellow-100 text-yellow-700">해결중</span>
			{/if}

			{#if autoRetryBlocked}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-red-100 text-red-700" title={mergeMessage ?? mergeReason ?? metaTitle}>
					자동 재시도 차단
				</span>
			{/if}

			{#if staleBadgeLabel()}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-muted text-muted-foreground" title={metaTitle}>
					{staleBadgeLabel()}
				</span>
			{/if}

			{#if needsPostMergeFollowup}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-amber-100 text-amber-800" title={metaTitle}>
					후처리 필요
				</span>
			{/if}

			{#if gateEvidenceLabel()}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-red-100 text-red-700" title={gateEvidenceTitle()}>
					{gateEvidenceLabel()}
				</span>
			{/if}

			{#if orphanAlive}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-orange-100 text-orange-700" title={metaTitle}>
					Redis 상태 소실
				</span>
			{:else if redisMissing && logFileFound}
				<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] bg-sky-100 text-sky-700" title={metaTitle}>
					로그 복구
				</span>
			{/if}

			{#if elapsed}
				<span class="ml-auto shrink-0 text-[10px] text-muted-foreground">{elapsed}</span>
			{/if}
		</div>

		{#if running}
			<button
				class="shrink-0 px-2 py-0.5 rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors text-[10px]"
				onclick={handleStop}
				disabled={stopping || killing}
			>
				{stopping ? '중지 중...' : '중지'}
			</button>
			<button
				class="shrink-0 px-2 py-0.5 rounded border border-red-400 text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors text-[10px] font-bold"
				onclick={handleKill}
				disabled={stopping || killing}
				title="강제 종료 (SIGKILL) — 진행 중인 작업이 유실됩니다"
			>
				{killing ? '종료 중...' : '강제'}
			</button>
		{:else if exitReason && !['completed', 'stopped', 'archived'].includes(exitReason) && onRestart}
			<button
				class="shrink-0 px-2 py-0.5 rounded border border-blue-300 text-blue-700 hover:bg-blue-100 transition-colors text-[10px] font-bold"
				onclick={onRestart}
				title="동일 plan으로 재실행"
			>
				재실행
			</button>
		{/if}
	</div>
	{#if stopError}
		<div class="px-3 py-1 text-xs text-red-600 bg-red-50 border-b border-red-100">{stopError}</div>
	{/if}

	{#if !running && error}
		<div class="px-3 py-1.5 text-xs text-red-700 bg-red-50 border-b border-red-100 truncate" title={error}>
			{error}
		</div>
	{/if}

	{#if needsPostMergeFollowup}
		<div class="px-3 py-1.5 text-xs text-amber-800 bg-amber-50 border-b border-amber-200">
			후처리 필요: T4/T5 잔여 {remainingPostMergeTasks ?? 0}개가 남아 있습니다.
		</div>
	{/if}

	{#if !running && mergeStatus === 'error' && (remainingPostMergeTasks ?? 0) > 0}
		<div class="px-3 py-1.5 text-xs text-red-800 bg-red-50 border-b border-red-200">
			후처리 차단: {mergeReason ?? 'unknown_merge_error'} · 잔여 {remainingPostMergeTasks ?? 0}개
		</div>
	{/if}

	{#if autoRetryBlocked}
		<div class="px-3 py-1.5 text-xs text-red-800 bg-red-50 border-b border-red-200">
			같은 사유 반복으로 자동 재시도가 차단됐습니다. force retry 또는 clean branch 재구성이 필요합니다.
		</div>
	{/if}

	{#if mergeStatus === 'resolving'}
		<div class="flex items-center gap-2 px-3 py-2 bg-yellow-50 border-b border-yellow-200 text-xs">
			<svg class="animate-spin h-3 w-3 text-yellow-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
			</svg>
			<span class="text-yellow-700 font-medium">충돌 자동 해결 중...</span>
		</div>
	{:else if mergeStatus === 'fixing'}
		<div class="flex items-center gap-2 px-3 py-2 bg-yellow-50 border-b border-yellow-200 text-xs">
			<svg class="animate-spin h-3 w-3 text-yellow-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
			</svg>
			<span class="text-yellow-700 font-medium">테스트 실패 자동 수정 중...</span>
		</div>
	{:else if mergeStatus === 'approval_required'}
		<div class="flex flex-col gap-1.5 px-3 py-2 bg-yellow-50 border-b border-yellow-200 text-xs">
			<div class="flex items-center gap-2 flex-wrap">
				<span class="text-yellow-800 font-medium">실행 중 서비스와 겹치는 변경이라 승인 필요</span>
				<span class="text-yellow-700/70 text-[10px]">자동 수정 대상 아님 — 사람 판단 필요</span>
				<button
					class="px-2 py-0.5 rounded border border-yellow-400 text-yellow-900 bg-yellow-100 hover:bg-yellow-200 disabled:opacity-50 transition-colors font-medium"
					onclick={handleApproveServiceLockAndRetryMerge}
					disabled={retryingMerge}
					title="실행 중 서비스와 겹치는 파일 변경을 확인하고, 같은 runner/worktree로 머지를 1회 재시도합니다 (approve_service_lock one-shot override)"
					aria-label={retryingMerge ? '승인 후 머지 재시도 진행 중' : '위험 확인 후 같은 runner/worktree로 머지 재시도 (1회)'}
				>
					{retryingMerge ? '승인 후 재시도 중...' : '위험 확인 후 머지 재시도'}
				</button>
				<button
					class="px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted transition-colors"
					onclick={handleCleanupWorktree}
					title="머지 재시도가 아닌 worktree 정리(삭제)입니다. 승인 없이 작업을 취소할 때 사용하세요."
				>
					Worktree 정리 (취소)
				</button>
			</div>
			{#if gateEvidenceSummary?.changed?.length || gateEvidenceSummary?.running?.length}
				<div class="flex flex-col gap-0.5 text-[11px] text-yellow-900/80 font-mono bg-yellow-100/60 rounded px-2 py-1">
					{#if gateEvidenceSummary?.changed?.length}
						<div class="flex gap-1 flex-wrap items-start">
							<span class="text-yellow-700 shrink-0">변경:</span>
							<span class="break-all">{gateEvidenceSummary.changed.join(', ')}</span>
						</div>
					{/if}
					{#if gateEvidenceSummary?.running?.length}
						<div class="flex gap-1 flex-wrap items-start">
							<span class="text-yellow-700 shrink-0">실행 중:</span>
							<span class="break-all">{gateEvidenceSummary.running.join(', ')}</span>
						</div>
					{/if}
					{#if mergeReason === 'service_lock' && (!gateEvidenceSummary?.changed?.length && !gateEvidenceSummary?.running?.length)}
						<div class="text-yellow-700/70">service_lock — changed/running evidence 미포함</div>
					{/if}
				</div>
			{:else if mergeReason || mergeMessage}
				<div class="text-[11px] text-yellow-900/80 break-all" title={mergeMessage ?? mergeReason ?? ''}>
					{mergeMessage ?? mergeReason}
				</div>
			{/if}
			{#if mergeMessage && mergeMessage.includes('[rebase_failed')}
				<div class="text-[11px] text-orange-700/80" title="rebase 충돌도 함께 발생 (근본 원인은 별도 plan에서 추적)">
					rebase 충돌도 함께 발생 (별도 plan으로 추적)
				</div>
			{/if}
			{#if divergeEvidenceText}
				<div class="text-[11px] text-yellow-700/80 font-mono" title="plan branch diverge evidence">
					{divergeEvidenceText}
				</div>
			{/if}
			{#if gateEvidenceSummary?.rebase_conflict}
				<div class="text-[11px] text-yellow-700/80">
					rebase 충돌도 함께 발생 (별도 plan으로 추적)
				</div>
			{/if}
		</div>
	{:else if ['conflict', 'test_failed', 'error'].includes(mergeStatus ?? '')}
		<div class="flex items-center gap-2 px-3 py-2 bg-red-50 border-b border-red-200 text-xs">
			<span class="text-red-700 font-medium">
				{#if mergeStatus === 'conflict'}머지 충돌이 발생했습니다.
				{:else if mergeStatus === 'test_failed'}머지 후 테스트가 실패했습니다.
				{:else}머지 중 오류가 발생했습니다.{/if}
			</span>
			{#if mergeStatus === 'conflict'}
				<button
					class="px-2 py-0.5 rounded border border-blue-300 text-blue-700 hover:bg-blue-100 disabled:opacity-50 transition-colors"
					onclick={handleResolveConflict}
					disabled={resolvingConflict}
				>
					{resolvingConflict ? '해결 중...' : '자동 해결'}
				</button>
			{/if}
			<button
				class="px-2 py-0.5 rounded border border-red-300 text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors"
				onclick={handleRetryMerge}
				disabled={retryingMerge}
			>
				{retryingMerge ? '재시도 중...' : '머지 재시도'}
			</button>
			<button
				class="px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted transition-colors"
				onclick={handleCleanupWorktree}
			>
				Worktree 정리
			</button>
		</div>
	{/if}

	{#if !running && branch && worktreePath && worktreeExists !== false && branchExists !== false && !['conflict', 'test_failed', 'error', 'resolving', 'fixing', 'approval_required'].includes(mergeStatus ?? '')}
		<div class="flex items-center gap-2 px-3 py-1.5 bg-muted/50 border-b border-border text-xs">
			<button
				class="px-2 py-0.5 rounded border border-purple-300 text-purple-700 hover:bg-purple-100 disabled:opacity-50 transition-colors"
				onclick={handleDirectMerge}
				disabled={directMerging}
				title="worktree가 살아있을 때 직접 머지 실행"
			>
				{directMerging ? '머지 중...' : '직접 머지'}
			</button>
		</div>
	{/if}

	{#if !running && mergeStatus !== 'approval_required' && worktreeExists === false}
		<div class="px-3 py-1.5 text-xs text-muted-foreground bg-muted/50 border-b border-border">
			삭제된 worktree의 과거 실행 기록입니다. 직접 머지는 새 worktree에서 다시 실행해야 합니다.
		</div>
	{:else if !running && mergeStatus !== 'approval_required' && branchExists === false}
		<div class="px-3 py-1.5 text-xs text-muted-foreground bg-muted/50 border-b border-border">
			branch가 남아 있지 않은 과거 실행 기록입니다.
		</div>
	{/if}

	{#if mergeError}
		<div class="px-3 py-1 text-xs text-red-600 bg-red-50 border-b border-red-100">{mergeError}</div>
	{/if}

	{#if orphan}
		<div class="flex items-center gap-2 px-3 py-2 bg-orange-50 border-b border-orange-200 text-xs">
			<span class="text-orange-700 font-medium">프로세스 종료 후 워크플로우가 정리되지 않았습니다.</span>
			<button class="px-2 py-0.5 rounded border border-orange-300 text-orange-700 hover:bg-orange-100 transition-colors" onclick={handleOrphanReset}>리셋</button>
		</div>
	{/if}

	{#if orphanAlive}
		<div class="flex items-center gap-2 px-3 py-1.5 text-xs text-orange-700 bg-orange-50 border-b border-orange-200">
			<span class="font-medium">상태 소실</span>
			<span class="min-w-0 flex-1 truncate" title={metaTitle}>
				Redis runner 상태는 소실됐지만 로그 또는 live process 근거가 남아 있습니다.
			</span>
			{#if onReattach}
				<button
					class="px-2 py-0.5 rounded border border-orange-300 text-orange-800 hover:bg-orange-100 disabled:opacity-50 transition-colors"
					onclick={onReattach}
					disabled={!canReattach}
					title="Redis active runner 상태로 재연결"
				>
					재연결
				</button>
			{/if}
			{#if onKillOrphan}
				<button
					class="px-2 py-0.5 rounded border border-red-300 text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors"
					onclick={onKillOrphan}
					disabled={!canForceKill}
					title="재연결하지 않고 live child를 강제 종료"
				>
					강제 종료
				</button>
			{/if}
		</div>
	{:else if redisMissing && logFileFound}
		<div class="px-3 py-1.5 text-xs text-sky-700 bg-sky-50 border-b border-sky-200">
			Runner 목록에서는 빠졌지만 기존 로그를 복구했습니다.
		</div>
	{/if}

	<!-- 로그 뷰어 -->
	<div class="flex-1 min-h-0">
		<LogViewer bind:this={logViewer} {runnerId} planFile={planFile ?? undefined} {running} {mergeStatus} {mergeReason} {mergeMessage} {trigger} {engine} {worktreePath} {branch} {executionCount} mode="managed" {onBatchPlansChange} />
	</div>
</div>
