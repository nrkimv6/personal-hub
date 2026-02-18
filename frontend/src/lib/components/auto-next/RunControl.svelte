<script lang="ts">
	import { autoNextRunnerApi, autoNextPlanApi } from '$lib/api';
	import type { AutoNextRunStatusResponse, AutoNextPlanFileResponse } from '$lib/api';

	interface Props {
		status: AutoNextRunStatusResponse | null;
		plans: AutoNextPlanFileResponse[];
		onStatusChange: () => void;
	}

	let { status, plans, onStatusChange }: Props = $props();

	let mode = $state<'single' | 'all'>('single');
	let selectedPlan = $state('');
	let maxCycles = $state(0);
	let until = $state('');
	let dryRun = $state(false);
	let parallel = $state(false);
	let projects = $state('');
	let actionLoading = $state(false);
	let actionError = $state<string | null>(null);

	// Elapsed timer
	let elapsed = $state('00:00:00');
	let elapsedInterval: ReturnType<typeof setInterval> | null = null;

	$effect(() => {
		if (status?.running && status.start_time) {
			updateElapsed(status.start_time);
			if (elapsedInterval) clearInterval(elapsedInterval);
			elapsedInterval = setInterval(() => updateElapsed(status.start_time!), 1000);
		} else {
			if (elapsedInterval) {
				clearInterval(elapsedInterval);
				elapsedInterval = null;
			}
			elapsed = '00:00:00';
		}
		return () => {
			if (elapsedInterval) {
				clearInterval(elapsedInterval);
				elapsedInterval = null;
			}
		};
	});

	function updateElapsed(startTime: string) {
		const diff = Date.now() - new Date(startTime).getTime();
		const h = Math.floor(diff / 3600000);
		const m = Math.floor((diff % 3600000) / 60000);
		const s = Math.floor((diff % 60000) / 1000);
		elapsed = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
	}

	async function handleStart() {
		if (mode === 'single' && !selectedPlan) {
			actionError = 'Plan 파일을 선택하세요';
			return;
		}
		actionLoading = true;
		actionError = null;
		try {
			await autoNextRunnerApi.start({
				plan_file: mode === 'single' ? selectedPlan : null,
				max_cycles: maxCycles || 0,
				until: until || null,
				dry_run: dryRun,
				parallel: mode === 'all' ? true : parallel,
				projects: projects || null
			});
			onStatusChange();
		} catch (e) {
			actionError = e instanceof Error ? e.message : '시작 실패';
		} finally {
			actionLoading = false;
		}
	}

	async function handleStop() {
		if (!confirm('실행을 중지하시겠습니까?')) return;
		actionLoading = true;
		actionError = null;
		try {
			await autoNextRunnerApi.stop();
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
		try {
			await autoNextPlanApi.sync();
			onStatusChange();
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
			const result = await autoNextRunnerApi.resetState(fullReset);
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
		<div class="text-xs text-red-600 bg-red-50 rounded p-2">{actionError}</div>
	{/if}

	<!-- Status Header -->
	<div class="flex items-center justify-between">
		<div class="flex items-center gap-3">
			<div class="w-2.5 h-2.5 rounded-full {status?.running ? 'bg-green-500 animate-pulse' : 'bg-gray-400'}"></div>
			<span class="text-sm font-medium">{status?.running ? '실행 중' : '중지'}</span>
			{#if status?.pid}
				<span class="text-xs text-gray-500 font-mono">PID {status.pid}</span>
			{/if}
		</div>
		{#if status?.running}
			<div class="flex items-center gap-3 text-xs text-gray-500">
				<span class="flex items-center gap-1">
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
					Cycle {status.current_cycle ?? '-'}
				</span>
				<span class="flex items-center gap-1">
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
					{elapsed}
				</span>
			</div>
		{/if}
	</div>

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
		>
			<option value="single">단일 Plan</option>
			<option value="all">전체 실행</option>
		</select>
	</div>

	<!-- Options Row -->
	<div class="flex items-center gap-4 flex-wrap text-xs">
		{#if mode === 'single'}
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
		<div class="flex items-center gap-2 text-xs">
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
