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

	// Phase 2: elapsed 타이머
	let elapsed = $state('');
	let elapsedInterval: ReturnType<typeof setInterval> | null = null;

	$effect(() => {
		if (status?.running && status.start_time) {
			// 즉시 1회 계산
			updateElapsed(status.start_time);
			// 매 초 업데이트
			if (elapsedInterval) clearInterval(elapsedInterval);
			elapsedInterval = setInterval(() => updateElapsed(status.start_time!), 1000);
		} else {
			if (elapsedInterval) {
				clearInterval(elapsedInterval);
				elapsedInterval = null;
			}
			elapsed = '';
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
		const totalSec = Math.floor(diff / 1000);
		const h = Math.floor(totalSec / 3600);
		const m = Math.floor((totalSec % 3600) / 60);
		const s = totalSec % 60;
		if (h > 0) {
			elapsed = `${h}h ${m}m ${s}s`;
		} else if (m > 0) {
			elapsed = `${m}m ${s}s`;
		} else {
			elapsed = `${s}s`;
		}
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

<div class="bg-white rounded-lg border p-3">
	<h2 class="font-semibold mb-2 text-sm">실행 제어</h2>

	{#if actionError}
		<div class="text-xs text-red-600 bg-red-50 rounded p-2 mb-2">{actionError}</div>
	{/if}

	{#if status?.running}
		<!-- Phase 2: 실행 중 상태를 한 줄 헤더로 압축 -->
		<div class="space-y-2">
			<div class="flex items-center gap-3 text-sm bg-green-50 rounded px-3 py-2">
				<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse shrink-0"></span>
				<span class="font-medium text-green-800">Running</span>
				<span class="text-gray-500">●</span>
				<span class="text-gray-600">PID: <span class="font-mono">{status.pid}</span></span>
				<span class="text-gray-400">|</span>
				<span class="text-gray-600">Cycle: {status.current_cycle ?? '-'}</span>
				<span class="text-gray-400">|</span>
				<span class="text-gray-600">Elapsed: <span class="font-mono">{elapsed || '...'}</span></span>
				{#if status.plan_file}
					<span class="text-gray-400">|</span>
					<span class="text-gray-500 truncate text-xs" title={status.plan_file}>{status.plan_file.split(/[\\/]/).pop()}</span>
				{/if}
			</div>
			<!-- Phase 2: 버튼 행을 한 줄로 압축 -->
			<div class="flex items-center gap-2">
				<button
					class="px-3 py-1.5 rounded text-sm font-medium text-white bg-red-500 hover:bg-red-600 disabled:opacity-50 transition-colors"
					onclick={handleStop}
					disabled={actionLoading}
				>
					{actionLoading ? '중지 중...' : '■ 중지'}
				</button>
				<span class="text-gray-300">|</span>
				<button
					class="px-3 py-1.5 rounded text-sm font-medium text-white bg-blue-500 hover:bg-blue-600 disabled:opacity-50 transition-colors"
					onclick={handleSync}
					disabled={actionLoading}
				>
					{actionLoading ? '동기화 중...' : '↻ 재동기화'}
				</button>
			</div>
		</div>
	{:else}
		<!-- Phase 2: 중지 상태 - 한 줄 압축 폼 -->
		<div class="space-y-2">
			<!-- Phase 2: 버튼 행 + 모드 선택 한 줄 -->
			<div class="flex items-center gap-2 flex-wrap">
				<!-- 모드 Select (탭 UI → 인라인 Select) -->
				<select
					class="border rounded px-2 py-1.5 text-xs bg-white"
					bind:value={mode}
				>
					<option value="single">단일 Plan</option>
					<option value="all">전체 실행</option>
				</select>

				<button
					class="px-3 py-1.5 rounded text-sm font-medium text-white bg-green-500 hover:bg-green-600 disabled:opacity-50 transition-colors"
					onclick={handleStart}
					disabled={actionLoading || (mode === 'single' && !selectedPlan)}
				>
					{actionLoading ? '시작 중...' : mode === 'all' ? '▶ 전체 실행' : '▶ 시작'}
				</button>
				<span class="text-gray-300">|</span>
				<button
					class="px-3 py-1.5 rounded text-sm font-medium text-white bg-blue-500 hover:bg-blue-600 disabled:opacity-50 transition-colors"
					onclick={handleSync}
					disabled={actionLoading}
					title="Plan 파일과 TODO.md를 SQLite 큐에 동기화합니다"
				>
					{actionLoading ? '동기화 중...' : '↻ 동기화'}
				</button>
				<button
					class="px-3 py-1.5 rounded text-sm font-medium text-white bg-yellow-500 hover:bg-yellow-600 disabled:opacity-50 transition-colors"
					onclick={() => handleResetState(false)}
					disabled={actionLoading}
					title="RUNNING 상태를 강제로 초기화하고 미완료 작업을 PENDING으로 복구합니다."
				>
					{actionLoading ? '초기화 중...' : '초기화'}
				</button>
				<button
					class="px-3 py-1.5 rounded text-sm font-medium text-white bg-red-500 hover:bg-red-600 disabled:opacity-50 transition-colors"
					onclick={() => handleResetState(true)}
					disabled={actionLoading}
					title="모든 작업 기록을 삭제하고 완전히 초기화합니다."
				>
					{actionLoading ? '삭제 중...' : '전체 리셋'}
				</button>
			</div>

			<!-- Phase 2: 옵션 행을 한 줄로 압축 -->
			<div class="flex items-center gap-3 text-xs flex-wrap">
				{#if mode === 'single'}
					<!-- Plan Select compact -->
					<select
						class="border rounded px-2 py-1 text-xs w-40 bg-white"
						bind:value={selectedPlan}
					>
						<option value="">Plan 선택...</option>
						{#each plans as plan}
							<option value={plan.path}>{plan.filename} ({plan.progress.percent}%)</option>
						{/each}
					</select>
				{:else}
					<span class="text-gray-400 text-xs">모든 미완료 Plan 자동 실행</span>
				{/if}
				<span class="text-gray-300">|</span>
				<label class="flex items-center gap-1 text-gray-600">
					<span>Max:</span>
					<input
						type="number"
						class="border rounded px-1.5 py-0.5 w-16 text-xs"
						bind:value={maxCycles}
						min="0"
						placeholder="∞"
					/>
				</label>
				<label class="flex items-center gap-1 text-gray-600">
					<span>Until:</span>
					<input
						type="time"
						class="border rounded px-1.5 py-0.5 text-xs"
						bind:value={until}
					/>
				</label>
				<label class="flex items-center gap-1.5 text-gray-600 cursor-pointer">
					<input type="checkbox" bind:checked={dryRun} class="rounded" />
					<span>Dry Run</span>
				</label>
				{#if mode === 'single'}
					<label class="flex items-center gap-1.5 text-gray-600 cursor-pointer">
						<input type="checkbox" bind:checked={parallel} class="rounded" />
						<span>병렬</span>
					</label>
				{/if}
			</div>

			{#if (mode === 'single' && parallel) || mode === 'all'}
				<div class="flex items-center gap-2 text-xs">
					<label class="text-gray-600 shrink-0">프로젝트:</label>
					<input
						type="text"
						class="flex-1 border rounded px-2 py-1 text-xs"
						bind:value={projects}
						placeholder="쉼표 구분 (비우면 전체)"
					/>
				</div>
			{/if}
		</div>
	{/if}
</div>
