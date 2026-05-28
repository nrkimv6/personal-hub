<script lang="ts">
	import { Play, RefreshCw, Square } from 'lucide-svelte';
	import type { DevRunnerReadinessResponse } from '$lib/api';

	type RunAction = 'start' | 'sync' | 'reset' | 'fullReset' | 'stop' | 'forceStop';

	interface Props {
		status: { redis_connected: boolean; listener_alive: boolean } | null;
		readiness?: DevRunnerReadinessResponse | null;
		anyRunning: boolean;
		activeAction: RunAction | null;
		mode: 'single' | 'all';
		selectedPlan: string;
		selectedPlanArchived: boolean;
		onStop: () => void;
		onSync: () => void;
		onReset: () => void;
		onFullReset: () => void;
		onStart: () => void;
	}

	let {
		status,
		readiness = null,
		anyRunning,
		activeAction,
		mode,
		selectedPlan,
		selectedPlanArchived,
		onStop,
		onSync,
		onReset,
		onFullReset,
		onStart
	}: Props = $props();

	let actionLoading = $derived(activeAction !== null);
	const isActive = (action: RunAction) => activeAction === action;

	let startDisabled = $derived(
		actionLoading ||
			(mode === 'single' && (!selectedPlan || selectedPlanArchived)) ||
			readiness?.can_start === false ||
			!status?.redis_connected ||
			!status?.listener_alive
	);

	let startLabel = $derived(isActive('start') ? '시작 중...' : mode === 'all' ? '전체 실행' : '시작');
	let startTitle = $derived(
		!status?.redis_connected
			? 'Redis 미연결'
			: !status?.listener_alive
				? 'Listener 미실행'
				: readiness?.can_start === false
					? readiness.items.find((item) => item.severity === 'blocker')?.message ?? 'Readiness 차단 항목이 있습니다'
					: actionLoading
						? '실행 요청 처리 중'
						: mode === 'single' && !selectedPlan
							? 'Plan을 선택하세요'
							: mode === 'single' && selectedPlanArchived
								? '아카이브된 Plan은 실행할 수 없습니다'
								: '실행'
	);
</script>

<div class="shrink-0 border-t border-border bg-card px-5 py-3">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="flex flex-wrap items-center gap-2">
			{#if anyRunning}
				<button
					type="button"
					class="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium bg-red-50 text-red-700 border border-red-200 transition-colors hover:bg-red-100 disabled:opacity-50"
					onclick={onStop}
					disabled={actionLoading}
				>
					<Square class="h-3.5 w-3.5" />
					{isActive('stop') ? '중지 중...' : '중지'}
				</button>
			{/if}

			{#if !anyRunning}
				<button
					type="button"
					class="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium border border-border text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
					onclick={onReset}
					disabled={actionLoading}
					title="RUNNING 상태를 강제로 초기화하고 미완료 작업을 PENDING으로 복구합니다."
				>
					{isActive('reset') ? '초기화 중...' : '초기화'}
				</button>

				<button
					type="button"
					class="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium border border-border text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
					onclick={onFullReset}
					disabled={actionLoading}
					title="모든 작업 기록을 삭제하고 완전히 초기화합니다."
				>
					{isActive('fullReset') ? '삭제 중...' : '전체 리셋'}
				</button>
			{/if}
		</div>

		<div class="flex flex-wrap items-center gap-2">
			<button
				type="button"
				class="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium border border-border text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
				onclick={onSync}
				disabled={actionLoading}
				title="Plan 파일과 plans ledger를 SQLite 큐에 동기화합니다"
			>
				<RefreshCw class="h-3.5 w-3.5" />
				{isActive('sync') ? '동기화 중...' : '동기화'}
			</button>

			<button
				type="button"
				class="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-mono font-semibold bg-green-50 text-green-700 border border-green-200 transition-colors hover:bg-green-100 disabled:opacity-50"
				onclick={onStart}
				disabled={startDisabled}
				title={startTitle}
			>
				<Play class="h-3.5 w-3.5" />
				{startLabel}
			</button>
		</div>
	</div>
</div>
