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

	function formatTime(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('ko-KR');
	}
</script>

<div class="bg-white rounded-lg border p-4">
	<h2 class="font-semibold mb-3">실행 제어</h2>

	{#if actionError}
		<div class="text-sm text-red-600 bg-red-50 rounded p-2 mb-3">{actionError}</div>
	{/if}

	{#if status?.running}
		<!-- 실행 중 상태 -->
		<div class="space-y-3">
			<div class="grid grid-cols-2 gap-2 text-sm">
				<div class="text-gray-500">PID</div>
				<div class="font-mono">{status.pid}</div>
				<div class="text-gray-500">Plan</div>
				<div class="truncate" title={status.plan_file || '전체 실행'}>{status.plan_file || '전체 실행'}</div>
				<div class="text-gray-500">시작 시각</div>
				<div>{formatTime(status.start_time)}</div>
				<div class="text-gray-500">현재 사이클</div>
				<div>{status.current_cycle ?? '-'}</div>
			</div>
			<div class="grid grid-cols-2 gap-2">
				<button
					class="py-2 rounded-lg font-medium text-white bg-blue-500 hover:bg-blue-600 disabled:opacity-50 transition-colors"
					onclick={handleSync}
					disabled={actionLoading}
				>
					{actionLoading ? '동기화 중...' : '재동기화'}
				</button>
				<button
					class="py-2 rounded-lg font-medium text-white bg-red-500 hover:bg-red-600 disabled:opacity-50 transition-colors"
					onclick={handleStop}
					disabled={actionLoading}
				>
					{actionLoading ? '중지 중...' : '중지'}
				</button>
			</div>
		</div>
	{:else}
		<!-- 중지 상태 - 시작 폼 -->
		<div class="space-y-3">
			<!-- 모드 선택 -->
			<div class="flex rounded-lg border text-sm overflow-hidden">
				<button
					class="flex-1 px-3 py-1.5 transition-colors {mode === 'single' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
					onclick={() => (mode = 'single')}
				>
					단일 Plan
				</button>
				<button
					class="flex-1 px-3 py-1.5 transition-colors {mode === 'all' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
					onclick={() => (mode = 'all')}
				>
					전체 실행
				</button>
			</div>

			{#if mode === 'single'}
				<div>
					<label class="block text-sm text-gray-600 mb-1" for="plan-select">Plan 파일</label>
					<select
						id="plan-select"
						class="w-full border rounded-lg px-3 py-2 text-sm"
						bind:value={selectedPlan}
					>
						<option value="">선택...</option>
						{#each plans as plan}
							<option value={plan.path}>{plan.filename} ({plan.progress.percent}%)</option>
						{/each}
					</select>
				</div>
			{:else}
				<div class="text-sm text-gray-500 bg-gray-50 rounded-lg p-3">
					모든 미완료 Plan 파일을 순차적으로 실행합니다.
				</div>
			{/if}

			<div class="grid grid-cols-2 gap-3">
				<div>
					<label class="block text-sm text-gray-600 mb-1" for="max-cycles">최대 사이클</label>
					<input
						id="max-cycles"
						type="number"
						class="w-full border rounded-lg px-3 py-2 text-sm"
						bind:value={maxCycles}
						min="0"
						placeholder="0 = 무제한"
					/>
				</div>
				<div>
					<label class="block text-sm text-gray-600 mb-1" for="until-time">종료 시각</label>
					<input
						id="until-time"
						type="time"
						class="w-full border rounded-lg px-3 py-2 text-sm"
						bind:value={until}
					/>
				</div>
			</div>
			<div class="flex gap-4">
				<label class="flex items-center gap-2 text-sm text-gray-600">
					<input type="checkbox" bind:checked={dryRun} />
					Dry Run
				</label>
				{#if mode === 'single'}
					<label class="flex items-center gap-2 text-sm text-gray-600">
						<input type="checkbox" bind:checked={parallel} />
						병렬 실행
					</label>
				{/if}
			</div>
			{#if (mode === 'single' && parallel) || mode === 'all'}
				<div>
					<label class="block text-sm text-gray-600 mb-1" for="projects">프로젝트 (쉼표 구분)</label>
					<input
						id="projects"
						type="text"
						class="w-full border rounded-lg px-3 py-2 text-sm"
						bind:value={projects}
						placeholder="예: memo-alarm,activity-hub (비우면 전체)"
					/>
				</div>
			{/if}
			<div class="grid grid-cols-3 gap-2">
				<button
					class="py-2 rounded-lg font-medium text-white bg-green-500 hover:bg-green-600 disabled:opacity-50 transition-colors"
					onclick={handleStart}
					disabled={actionLoading || (mode === 'single' && !selectedPlan)}
				>
					{actionLoading ? '시작 중...' : mode === 'all' ? '전체 실행 시작' : '시작'}
				</button>
				<button
					class="py-2 rounded-lg font-medium text-white bg-yellow-500 hover:bg-yellow-600 disabled:opacity-50 transition-colors"
					onclick={() => handleResetState(false)}
					disabled={actionLoading}
					title="RUNNING 상태를 강제로 초기화하고 미완료 작업을 PENDING으로 복구합니다."
				>
					{actionLoading ? '초기화 중...' : '상태 초기화'}
				</button>
				<button
					class="py-2 rounded-lg font-medium text-white bg-red-500 hover:bg-red-600 disabled:opacity-50 transition-colors"
					onclick={() => handleResetState(true)}
					disabled={actionLoading}
					title="모든 작업 기록을 삭제하고 완전히 초기화합니다."
				>
					{actionLoading ? '삭제 중...' : '전체 리셋'}
				</button>
			</div>
		</div>
	{/if}
</div>
