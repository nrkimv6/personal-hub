<script lang="ts">
	import { devRunnerRunnerApi, devRunnerPlanApi } from '$lib/api';
	import type { DevRunnerRunStatusResponse, DevRunnerPlanFileResponse } from '$lib/api';

	interface Props {
		status: DevRunnerRunStatusResponse | null;
		plans: DevRunnerPlanFileResponse[];
		onStatusChange: () => void;
		selectedPlan?: string;
	}

	let { status, plans, onStatusChange, selectedPlan = $bindable('') }: Props = $props();

	let mode = $state<'single' | 'all'>('single');
	let maxCycles = $state(0);

	// 실행 중인 plan 표시 정보
	let runningPlanName = $derived(
		!status?.running ? '' :
		status.plan_file === 'ALL' ? '전체 실행' :
		status.plan_file ? status.plan_file.split(/[\\/]/).pop() ?? '' : '실행 중'
	);
	let runningPlanProgress = $derived(
		status?.running && status.plan_file && status.plan_file !== 'ALL'
			? (plans.find(p => p.path === status!.plan_file)?.progress ?? null)
			: null
	);
	let until = $state('');
	let dryRun = $state(false);
	let parallel = $state(false);
	let projects = $state('');
	let actionLoading = $state(false);
	let actionError = $state<string | null>(null);
	let syncMessage = $state<string | null>(null);
	let forceStopNeeded = $state(false);

	async function handleStart() {
		if (mode === 'single' && !selectedPlan) {
			actionError = 'Plan 파일을 선택하세요';
			return;
		}
		actionLoading = true;
		actionError = null;
		forceStopNeeded = false;
		try {
			await devRunnerRunnerApi.start({
				plan_file: mode === 'single' ? selectedPlan : null,
				max_cycles: maxCycles || 0,
				until: until || null,
				dry_run: dryRun,
				parallel: mode === 'all' ? true : parallel,
				projects: projects || null
			});
			onStatusChange();
		} catch (e) {
			const msg = e instanceof Error ? e.message : '시작 실패';
			if (msg.includes('Already running')) {
				// 실제 실행 중 → 상태 즉시 새로고침 (중지 버튼이 자동으로 표시됨)
				onStatusChange();
				actionError = msg;
				forceStopNeeded = true;
			} else if (msg.includes('Redis') || msg.includes('listener') || msg.includes('503') || msg.includes('504')) {
				actionError = `${msg} — Redis와 dev-runner listener가 실행 중인지 확인하세요.`;
			} else {
				actionError = msg;
			}
		} finally {
			actionLoading = false;
		}
	}

	async function handleForceStop() {
		actionLoading = true;
		actionError = null;
		forceStopNeeded = false;
		try {
			await devRunnerRunnerApi.resetState(false);
			onStatusChange();
		} catch (e) {
			actionError = e instanceof Error ? e.message : '강제 중지 실패';
		} finally {
			actionLoading = false;
		}
	}

	async function handleStop() {
		if (!confirm('실행을 중지하시겠습니까?')) return;
		actionLoading = true;
		actionError = null;
		try {
			await devRunnerRunnerApi.stop();
			onStatusChange();
		} catch (e) {
			actionError = e instanceof Error ? e.message : '중지 실패';
		} finally {
			actionLoading = false;
		}
	}

	async function handleSync() {
		actionLoading = true;
		actionError = null;
		syncMessage = null;
		try {
			const result = await devRunnerPlanApi.sync();
			onStatusChange();
			const parts: string[] = [];
			if (result.added > 0) parts.push(`${result.added}개 추가`);
			if (result.removed > 0) parts.push(`${result.removed}개 제거`);
			if (result.updated > 0) parts.push(`${result.updated}개 변경`);
			syncMessage = parts.length > 0
				? `동기화 완료: ${parts.join(', ')} (총 ${result.synced}개)`
				: `동기화 완료: 변경 없음 (총 ${result.synced}개)`;
			setTimeout(() => { syncMessage = null; }, 5000);
		} catch (e) {
			actionError = e instanceof Error ? e.message : '동기화 실패';
		} finally {
			actionLoading = false;
		}
	}

	async function handleResetState(fullReset: boolean = false) {
		const msg = fullReset
			? '전체 리셋: 모든 작업 기록을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.'
			: 'RUNNING 상태를 초기화하시겠습니까?\n미완료 작업이 PENDING으로 복구됩니다.';
		if (!confirm(msg)) return;
		actionLoading = true;
		actionError = null;
		try {
			const result = await devRunnerRunnerApi.resetState(fullReset);
			console.log(`${result.reset_count}개 작업 ${fullReset ? '삭제' : '초기화'}됨`);
			onStatusChange();
		} catch (e) {
			actionError = e instanceof Error ? e.message : '초기화 실패';
		} finally {
			actionLoading = false;
		}
	}
</script>

<div class="flex flex-col gap-4">
	{#if actionError}
		<div class="text-xs text-red-600 bg-red-50 rounded p-2 flex items-center justify-between gap-2">
			<span>{actionError}</span>
			{#if forceStopNeeded}
				<button
					class="shrink-0 px-2 py-0.5 rounded border border-red-400 text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors"
					onclick={handleForceStop}
					disabled={actionLoading}
				>
					강제 중지
				</button>
			{/if}
		</div>
	{/if}
	{#if syncMessage}
		<div class="text-xs text-green-700 bg-green-50 rounded p-2">{syncMessage}</div>
	{/if}

	<!-- Controls Row -->
	<div class="flex items-center gap-2 flex-wrap">
		{#if status?.running}
			<button
				class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 disabled:opacity-50 transition-colors"
				onclick={handleStop}
				disabled={actionLoading}
			>
				<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
				{actionLoading ? '중지 중...' : '중지'}
			</button>
		{:else}
			<button
				class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 disabled:opacity-50 transition-colors"
				onclick={handleStart}
				disabled={actionLoading || (mode === 'single' && !selectedPlan)}
			>
				<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
				{actionLoading ? '시작 중...' : mode === 'all' ? '전체 실행' : '시작'}
			</button>
		{/if}

		<button
			class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
			onclick={handleSync}
			disabled={actionLoading}
			title="Plan 파일과 TODO.md를 SQLite 큐에 동기화합니다"
		>
			<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
			{actionLoading ? '동기화 중...' : '동기화'}
		</button>

		{#if !status?.running}
			<button
				class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
				onclick={() => handleResetState(false)}
				disabled={actionLoading}
				title="RUNNING 상태를 강제로 초기화하고 미완료 작업을 PENDING으로 복구합니다."
			>
				<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v6h6"/><path d="M3 13a9 9 0 1 0 3-7.7L3 8"/></svg>
				{actionLoading ? '초기화 중...' : '초기화'}
			</button>

			<button
				class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
				onclick={() => handleResetState(true)}
				disabled={actionLoading}
				title="모든 작업 기록을 삭제하고 완전히 초기화합니다."
			>
				{actionLoading ? '삭제 중...' : '전체 리셋'}
			</button>
		{/if}

		<div class="h-4 w-px bg-gray-200 mx-1"></div>

		<!-- Mode Select -->
		<select
			class="border rounded px-2 py-1.5 text-xs h-8 w-[120px]"
			bind:value={mode}
			disabled={status?.running}
		>
			<option value="single">단일 Plan</option>
			<option value="all">전체 실행</option>
		</select>
	</div>

	<!-- Options Row -->
	<div class="flex items-center gap-4 flex-wrap text-xs {status?.running ? 'opacity-50 pointer-events-none' : ''}">
		{#if status?.running}
			<!-- 실행 중: Plan 선택 대신 실행 정보 표시 -->
			<div class="flex items-center gap-2 opacity-100 pointer-events-none" style="opacity:1">
				<span class="text-gray-500 text-xs">Plan</span>
				<span class="inline-flex items-center gap-1.5 border border-green-200 bg-green-50 rounded px-2 py-1 text-xs font-mono text-green-700 h-7">
					<span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse shrink-0"></span>
					{runningPlanName}
					{#if runningPlanProgress}
						<span class="text-green-600 opacity-70">({runningPlanProgress.done}/{runningPlanProgress.total})</span>
					{/if}
				</span>
			</div>
		{:else if mode === 'single'}
			<div class="flex items-center gap-2">
				<label for="plan-select" class="text-gray-500 text-xs">Plan</label>
				<select
					id="plan-select"
					class="border rounded px-2 py-1 text-xs w-[200px] h-7 font-mono"
					bind:value={selectedPlan}
				>
					<option value="">Plan 선택...</option>
					{#each plans as plan}
						<option value={plan.path}>{plan.filename} ({plan.progress.percent}%)</option>
					{/each}
				</select>
			</div>
		{:else}
			<span class="text-gray-400 text-xs">모든 미완료 Plan 자동 실행</span>
		{/if}

		<div class="flex items-center gap-2">
			<label for="max-cycles" class="text-gray-500 text-xs">Max Cycles</label>
			<input
				id="max-cycles"
				type="number"
				class="border rounded px-1.5 py-0.5 w-16 h-7 text-xs font-mono"
				bind:value={maxCycles}
				min="0"
				placeholder="∞"
			/>
		</div>

		<div class="flex items-center gap-2">
			<label for="end-time" class="text-gray-500 text-xs">End Time</label>
			<input
				id="end-time"
				type="time"
				class="border rounded px-1.5 py-0.5 w-24 h-7 text-xs font-mono"
				bind:value={until}
			/>
		</div>

		<div class="flex items-center gap-2">
			<label class="relative inline-flex items-center cursor-pointer">
				<input type="checkbox" bind:checked={dryRun} class="sr-only peer" />
				<div class="w-8 h-4 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-blue-500"></div>
			</label>
			<span class="text-gray-500 text-xs flex items-center gap-1">
				<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>
				Dry Run
			</span>
		</div>

		{#if mode === 'single'}
			<label class="flex items-center gap-1.5 text-gray-500 cursor-pointer text-xs">
				<input type="checkbox" bind:checked={parallel} class="rounded" />
				<span>병렬</span>
			</label>
		{/if}
	</div>

	{#if (mode === 'single' && parallel) || mode === 'all'}
		<div class="flex items-center gap-2 text-xs {status?.running ? 'opacity-50 pointer-events-none' : ''}">
			<label class="text-gray-500 shrink-0" for="projects-input">프로젝트:</label>
			<input
				id="projects-input"
				type="text"
				class="flex-1 border rounded px-2 py-1 text-xs"
				bind:value={projects}
				placeholder="쉼표 구분 (비우면 전체)"
			/>
		</div>
	{/if}
</div>
