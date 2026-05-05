<script lang="ts">
	import { devRunnerPlanApi } from '$lib/api';
	import type { DevRunnerPlanFileResponse, DevRunnerRegisteredPathResponse } from '$lib/api';
	import { encodePathToBase64 } from '$lib/utils/encoding';
	import { confirm } from '$lib/stores/confirm';

	let doneLoadingPath = $state<string | null>(null);
	let doneMessage = $state<{ path: string; success: boolean; text: string; remaining?: number; total?: number; planStatus?: string } | null>(null);
	let batchDoneLoading = $state(false);
	let batchVerifyDoneLoading = $state(false);

	async function handleDone(e: Event, plan: DevRunnerPlanFileResponse) {
		e.stopPropagation();
		if (!await confirm({
			title: '완료 처리',
			message: '완료 처리를 실행하시겠습니까?\n아카이브 이동, TODO→DONE, 커밋이 수행됩니다.',
			confirmText: '실행'
		})) return;
		doneLoadingPath = plan.path;
		doneMessage = null;
		try {
			const result = await devRunnerPlanApi.done(encodePathToBase64(plan.path));
			doneMessage = {
				path: plan.path,
				success: result.success,
				text: result.message,
				remaining: result.remaining_tasks,
				total: result.total_tasks,
				planStatus: result.plan_status,
			};
			if (result.success) {
				onPlansChange?.();
				setTimeout(() => { doneMessage = null; }, 5000);
			}
		} catch (err: unknown) {
			doneMessage = { path: plan.path, success: false, text: err instanceof Error ? err.message : '완료 처리 실패' };
		} finally {
			doneLoadingPath = null;
		}
	}

	async function handleBatchDone() {
		// 백엔드가 무시 목록(구현완료 등) 포함 전체 대상 처리
		if (!await confirm({
			title: '완료 일괄 처리',
			message: '완료 가능한 plan을 일괄 완료 처리하시겠습니까?\n(구현완료 상태 포함)\n\n아카이브 이동, TODO→DONE, 커밋이 수행됩니다.',
			confirmText: '일괄 처리',
			variant: 'danger'
		})) return;
		batchDoneLoading = true;
		doneMessage = null;
		try {
			const result = await devRunnerPlanApi.batchDone();
			doneMessage = {
				path: '',
				success: result.failed === 0,
				text: `일괄 완료: ${result.success}개 성공${result.failed > 0 ? `, ${result.failed}개 실패` : ''}`
			};
			onPlansChange?.();
			setTimeout(() => { doneMessage = null; }, 5000);
		} catch (err: unknown) {
			doneMessage = { path: '', success: false, text: err instanceof Error ? err.message : '일괄 완료 실패' };
		} finally {
			batchDoneLoading = false;
		}
	}

	async function handleBatchVerifyDone() {
		if (!await confirm({
			title: '검증 기반 완료 처리',
			message: '코드베이스 검증 기반으로 완료 가능한 plan을 일괄 처리하시겠습니까?\n(파일 존재 여부 + 체크박스 기반 판정)\n\n아카이브 이동, TODO→DONE, 커밋이 수행됩니다.',
			confirmText: '일괄 처리',
			variant: 'danger'
		})) return;
		batchVerifyDoneLoading = true;
		doneMessage = null;
		try {
			const result = await devRunnerPlanApi.batchVerifyDone();
			doneMessage = {
				path: '',
				success: result.failed === 0,
				text: `검증 완료: ${result.success}개 성공${result.failed > 0 ? `, ${result.failed}개 실패` : ''}${result.total === 0 ? ' (대상 없음)' : ''}`
			};
			onPlansChange?.();
			setTimeout(() => { doneMessage = null; }, 5000);
		} catch (err: unknown) {
			doneMessage = { path: '', success: false, text: err instanceof Error ? err.message : '검증 완료 실패' };
		} finally {
			batchVerifyDoneLoading = false;
		}
	}

	function canDone(plan: DevRunnerPlanFileResponse): boolean {
		if (plan.path.includes('archive')) return false;
		const doneStatuses = ['구현완료', '완료', '수정 완료', '배포완료', '수정완료', '검토완료'];
		return (plan.progress != null && plan.progress.total > 0 && plan.progress.done === plan.progress.total)
			|| doneStatuses.includes(plan.status);
	}

	async function handleHold(e: Event, plan: DevRunnerPlanFileResponse) {
		e.stopPropagation();
		try {
			await devRunnerPlanApi.hold(encodePathToBase64(plan.path));
			onPlansChange?.();
		} catch { /* ignore */ }
	}

	async function handleUnhold(e: Event, plan: DevRunnerPlanFileResponse) {
		e.stopPropagation();
		try {
			await devRunnerPlanApi.unhold(encodePathToBase64(plan.path));
			onPlansChange?.();
			if (showIgnored) await loadIgnored();
		} catch { /* ignore */ }
	}

	interface BatchPlanItem {
		name: string;
		status: 'pending' | 'running' | 'done';
	}

	interface Props {
		plans: DevRunnerPlanFileResponse[];
		onPlansChange?: () => void;
		runningPlanFile?: string | null;
		lastPlanFile?: string | null;
		batchPlans?: BatchPlanItem[];
		onPlanModalOpen?: (plan: DevRunnerPlanFileResponse) => void;
	}

	let { plans, onPlansChange, runningPlanFile = null, lastPlanFile = null, batchPlans = [], onPlanModalOpen }: Props = $props();

	function parsePlanFilename(filename: string) {
		const match = filename.match(/^(\d{4}-\d{2}-\d{2})_(.+)$/);
		if (match) {
			return { date: match[1], name: match[2] };
		}
		return { date: null, name: filename };
	}

	function formatDate(date: string): string {
		const match = date.match(/^\d{4}-(\d{2})-(\d{2})$/);
		if (!match) return date;
		return `${parseInt(match[1])}/${parseInt(match[2])}`;
	}

	function isArchivePlan(plan: DevRunnerPlanFileResponse): boolean {
		return plan.path.includes('/archive/') || plan.path.includes('\\archive\\');
	}

	function getPlanItemBg(plan: DevRunnerPlanFileResponse, isRunning: boolean, isLastRun: boolean, batchStatus: string | null) {
		if (isArchivePlan(plan)) return 'bg-muted opacity-50 cursor-not-allowed';
		if (batchStatus === 'running') return 'border border-cyan-300 bg-cyan-50';
		if (isRunning) return 'border border-green-300 bg-green-50';
		if (batchStatus === 'done' || isLastRun) return 'bg-muted opacity-60';

		const status = plan.status;
		if (status === '구현중') return 'bg-blue-50/50 hover:bg-blue-100/50';
		if (status === '완료' || status === '배포완료') return 'bg-foreground text-background hover:bg-foreground/90';
		if (['구현완료', '수정 완료', '수정완료'].includes(status)) return 'bg-muted opacity-60 hover:opacity-100';

		return 'bg-card hover:bg-muted';
	}

	// batch plan name → status 매핑
	let batchStatusMap = $derived.by(() => {
		const map = new Map<string, 'pending' | 'running' | 'done'>();
		for (const bp of batchPlans) {
			map.set(bp.name, bp.status);
		}
		return map;
	});

	function getBatchStatus(plan: DevRunnerPlanFileResponse): 'pending' | 'running' | 'done' | null {
		if (batchPlans.length === 0) return null;
		// filename에서 확장자 제거하여 매칭
		const name = plan.filename.replace(/\.md$/, '');
		return batchStatusMap.get(name) ?? batchStatusMap.get(plan.filename) ?? null;
	}

	let showIgnored = $state(false);
	let editingPlans = $state(false);
	let ignoredPlans = $state<DevRunnerPlanFileResponse[]>([]);
	let ignoredLoading = $state(false);
	let showAddForm = $state(false);
	let newPath = $state('');
	let newPathType = $state<'plan' | 'archive'>('plan');
	let addError = $state<string | null>(null);
	let addLoading = $state(false);

	// 등록된 경로 목록
	let registeredPaths = $state<DevRunnerRegisteredPathResponse[]>([]);
	let registeredPathsLoading = $state(false);

	// Plan 인라인 팝업 제거 (모달로 대체)
	let summaryGeneratingPath = $state<string | null>(null);

	function handlePlanSelect(plan: DevRunnerPlanFileResponse) {
		onPlanModalOpen?.(plan);
	}

	async function handleGenerateSummary(e: Event, plan: DevRunnerPlanFileResponse) {
		e.stopPropagation();
		summaryGeneratingPath = plan.path;
		try {
			await devRunnerPlanApi.generateSummary(encodePathToBase64(plan.path));
			onPlansChange?.();
		} catch {
			// ignore
		} finally {
			summaryGeneratingPath = null;
		}
	}

	async function loadIgnored() {
		ignoredLoading = true;
		try {
			ignoredPlans = await devRunnerPlanApi.ignored();
		} catch {
			ignoredPlans = [];
		} finally {
			ignoredLoading = false;
		}
	}

	function toggleIgnored() {
		showIgnored = !showIgnored;
		if (showIgnored && ignoredPlans.length === 0) {
			loadIgnored();
		}
	}

	async function loadRegisteredPaths() {
		registeredPathsLoading = true;
		try {
			registeredPaths = await devRunnerPlanApi.listPaths();
		} catch {
			registeredPaths = [];
		} finally {
			registeredPathsLoading = false;
		}
	}

	async function handleAddPath() {
		if (!newPath.trim()) return;
		addLoading = true;
		addError = null;
		try {
			await devRunnerPlanApi.addPath(newPath.trim(), newPathType);
			newPath = '';
			onPlansChange?.();
			await loadRegisteredPaths();
		} catch (e) {
			addError = e instanceof Error ? e.message : '추가 실패';
		} finally {
			addLoading = false;
		}
	}

	async function handleRemovePath(e: Event, path: string) {
		e.stopPropagation();
		try {
			await devRunnerPlanApi.removePath(path);
			onPlansChange?.();
			await loadRegisteredPaths();
		} catch { /* ignore */ }
	}

	async function handleRemoveRegisteredPath(path: string) {
		try {
			await devRunnerPlanApi.removePath(path);
			onPlansChange?.();
			await loadRegisteredPaths();
		} catch { /* ignore */ }
	}

	async function handleIgnore(e: Event, path: string) {
		e.stopPropagation();
		try {
			await devRunnerPlanApi.ignore(encodePathToBase64(path));
			onPlansChange?.();
		} catch { /* ignore */ }
	}

	async function handleUnignore(e: Event, path: string) {
		e.stopPropagation();
		try {
			await devRunnerPlanApi.unignore(encodePathToBase64(path));
			onPlansChange?.();
			await loadIgnored();
		} catch { /* ignore */ }
	}

	function statusBadge(status: string): string {
		const map: Record<string, string> = {
			'구현중': 'bg-blue-100 text-blue-700 border border-blue-200',
			'구현완료': 'bg-green-100 text-green-700 border border-green-200',
			'검토완료': 'bg-purple-100 text-purple-700 border border-purple-200',
			'초안': 'bg-muted text-muted-foreground',
			'보류': 'bg-yellow-100 text-yellow-700 border border-yellow-200'
		};
		return map[status] || 'bg-muted text-muted-foreground';
	}

	let displayPlans = $derived.by(() => {
		const list = (showIgnored ? ignoredPlans : (plans ?? []));
		return [...list].sort((a, b) => {
			const aDone = a.status === '구현완료' ? 1 : 0;
			const bDone = b.status === '구현완료' ? 1 : 0;
			return aDone - bDone;
		});
	});
	let hasDoneablePlans = $derived((plans ?? []).some(p => canDone(p)));
</script>

<div class="flex flex-col gap-3 min-h-0 flex-1">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<span class="text-xs text-gray-500 font-medium uppercase tracking-wider">Plan Files</span>
		<div class="flex gap-1">
			{#if !showIgnored}
				<button
					class="h-6 px-2 text-[10px] rounded text-green-600 hover:bg-green-50 transition-colors inline-flex items-center gap-1 disabled:opacity-50"
					onclick={handleBatchDone}
					disabled={batchDoneLoading}
					title="완료 가능한 plan 일괄 아카이브"
				>
					{#if batchDoneLoading}
						<svg class="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-dashoffset="10"/></svg>
					{:else}
						<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
					{/if}
					일괄 완료
				</button>
				<button
					class="h-6 px-2 text-[10px] rounded text-blue-600 hover:bg-blue-50 transition-colors inline-flex items-center gap-1 disabled:opacity-50"
					onclick={handleBatchVerifyDone}
					disabled={batchVerifyDoneLoading}
					title="코드베이스 검증 기반으로 완료 가능한 plan 일괄 처리"
				>
					{#if batchVerifyDoneLoading}
						<svg class="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-dashoffset="10"/></svg>
					{:else}
						<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="9"/></svg>
					{/if}
					검증 완료
				</button>
			{/if}
			<button
				class="h-6 w-6 flex items-center justify-center rounded text-gray-500 hover:bg-gray-100 transition-colors"
				onclick={toggleIgnored}
				title={showIgnored ? '활성 plan 보기' : '무시 목록 보기'}
			>
				{#if showIgnored}
					<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
				{:else}
					<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
				{/if}
			</button>
			<button
				class="h-6 px-2 text-[10px] rounded transition-colors inline-flex items-center gap-1 {editingPlans ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-100'}"
				onclick={() => editingPlans = !editingPlans}
				title={editingPlans ? '편집 모드 끄기' : '편집 모드'}
				aria-pressed={editingPlans}
			>
				<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
				편집
			</button>
			<button
				class="h-6 px-2 text-[10px] rounded text-gray-500 hover:bg-gray-100 transition-colors inline-flex items-center gap-1"
				onclick={() => { showAddForm = !showAddForm; if (showAddForm) loadRegisteredPaths(); }}
			>
				<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
				추가
			</button>
		</div>
	</div>

	{#if showAddForm}
		<div class="p-2.5 bg-gray-50 rounded-lg space-y-2">
			{#if addError}
				<div class="text-xs text-red-600">{addError}</div>
			{/if}
			<input
				type="text"
				class="w-full border rounded px-2 py-1 text-xs"
				bind:value={newPath}
				placeholder="Plan 파일 또는 폴더 경로 (예: D:\work\project\...)"
			/>
			<div class="flex gap-2">
				<select
					bind:value={newPathType}
					class="text-xs px-2 py-1 border border-border rounded bg-background text-foreground focus:outline-none"
				>
					<option value="plan">plan</option>
					<option value="archive">archive</option>
				</select>
				<button
					class="text-xs px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
					onclick={handleAddPath}
					disabled={addLoading || !newPath.trim()}
				>
					{addLoading ? '추가 중...' : '추가'}
				</button>
				<button
					class="text-xs px-3 py-1 rounded bg-muted text-muted-foreground hover:bg-secondary"
					onclick={() => { showAddForm = false; addError = null; }}
				>
					취소
				</button>
			</div>

		<!-- 등록된 경로 목록 -->
		{#if registeredPathsLoading}
			<div class="text-[10px] text-gray-400">로딩 중...</div>
		{:else if registeredPaths.length > 0}
			<div class="border-t pt-2 mt-1 space-y-1 max-h-32 sm:max-h-40 overflow-y-auto">
				<div class="text-[10px] text-gray-400 font-medium uppercase tracking-wider">등록된 경로</div>
				{#each registeredPaths as ep}
					<div class="flex items-center gap-1.5 text-[10px]">
						<!-- 파일/폴더 아이콘 -->
						{#if ep.type === 'folder'}
							<svg class="w-3 h-3 shrink-0 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
						{:else}
							<svg class="w-3 h-3 shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
						{/if}
						<span class="truncate flex-1 text-muted-foreground" title={ep.path}>{ep.path}</span>
						<span class="shrink-0 text-gray-400 font-mono">{ep.plan_count}개</span>
						<button
							class="shrink-0 text-red-400 hover:text-red-600 px-1"
							onclick={() => handleRemoveRegisteredPath(ep.path)}
							title="등록 해제"
						>×</button>
					</div>
				{/each}
			</div>
		{/if}
		</div>
	{/if}

	{#if doneMessage}
		{@const hasRemaining = doneMessage.remaining !== undefined && doneMessage.remaining > 0}
		<div class="text-xs rounded p-2 {doneMessage.success
			? (hasRemaining ? 'text-amber-700 bg-amber-50' : 'text-green-700 bg-green-50')
			: 'text-red-600 bg-red-50'}">
			{#if doneMessage.success && doneMessage.total !== undefined}
				{#if hasRemaining}
					완료 처리 성공 — 남은 task: {doneMessage.remaining}/{doneMessage.total}
				{:else}
					완료 처리 성공 — 상태: {doneMessage.planStatus || '완료'}, {doneMessage.total}/{doneMessage.total} 완료
				{/if}
			{:else}
				{doneMessage.text}
			{/if}
		</div>
	{/if}

	{#if ignoredLoading}
		<div class="text-gray-400 text-sm text-center py-4">로딩 중...</div>
	{:else if displayPlans.length === 0}
		<p class="text-gray-400 text-sm">
			{showIgnored ? '무시된 Plan이 없습니다' : 'Plan 파일이 없습니다'}
		</p>
	{:else}
		<!-- Plan list (scrollable) -->
		<div class="flex-1 overflow-y-auto -mx-1 px-1">
			<div class="flex flex-col gap-1">
				{#each displayPlans as plan}
					{@const isArchive = isArchivePlan(plan)}
					{@const isRunning = runningPlanFile === plan.path}
					{@const isLastRun = !isRunning && lastPlanFile === plan.path}
					{@const isDone = plan.status === '구현완료'}
					{@const batchStatus = getBatchStatus(plan)}
					{@const parsedFilename = parsePlanFilename(plan.filename)}
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						onclick={() => { if (!isArchive) handlePlanSelect(plan); }}
						onkeydown={(e) => { if (!isArchive && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); handlePlanSelect(plan); } }}
						role="button"
						tabindex={isArchive ? -1 : 0}
						title={isArchive ? `아카이브됨: ${plan.path}` : plan.path}
						class="group flex min-h-[4rem] flex-col gap-1 rounded-md px-2.5 py-2 text-left transition-colors w-full
							{isArchive ? '' : 'cursor-pointer'}
							{getPlanItemBg(plan, isRunning, isLastRun, batchStatus)}"
					>
						<div class="flex w-full min-w-0 items-center gap-2">
							<!-- Running indicator dot -->
							{#if isRunning}
								<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse shrink-0"></span>
							{:else if plan.path_type === 'folder'}
								<svg class="w-3.5 h-3.5 shrink-0 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
							{:else}
								<svg class="w-3.5 h-3.5 shrink-0 {isArchive ? 'text-gray-300' : isLastRun ? 'text-gray-300' : 'text-gray-400'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
							{/if}
							<span class="min-w-0 flex-1 truncate text-xs font-medium {batchStatus === 'done' ? 'text-gray-400 line-through' : batchStatus === 'running' ? 'text-cyan-700' : isRunning ? 'text-green-800' : isLastRun ? 'text-gray-400 line-through' : isDone ? 'text-gray-400' : ''}">
								{parsedFilename.name}
							</span>
						</div>

						<div class="flex w-full min-w-0 items-center gap-1.5 pl-5 text-[10px] text-gray-400">
							{#if parsedFilename.date}
								<span class="shrink-0 font-mono">{formatDate(parsedFilename.date)}</span>
							{/if}
							{#if isArchive}
								<span class="shrink-0 font-mono px-1.5 py-0.5 rounded bg-gray-200 text-gray-400">아카이브</span>
							{:else if plan.status === '구현완료'}
								<span class="shrink-0 inline-flex items-center justify-center px-2 py-0.5 font-mono uppercase whitespace-nowrap rounded {statusBadge('구현완료')}">구현완료</span>
							{:else if showIgnored && plan.status === '보류'}
								<span class="shrink-0 inline-flex items-center justify-center px-2 py-0.5 font-mono uppercase whitespace-nowrap rounded {statusBadge('보류')}">보류</span>
							{/if}

							{#if batchStatus === 'running'}
								<span class="shrink-0 px-1 py-0 rounded text-cyan-600 bg-cyan-100">실행중</span>
							{:else if batchStatus === 'done'}
								<span class="shrink-0 text-gray-400">완료</span>
							{/if}
							<span class="shrink-0 font-mono {plan.progress != null && plan.progress.done === plan.progress.total && plan.progress.total > 0 ? 'text-emerald-600' : batchStatus === 'running' ? 'text-cyan-600' : isRunning ? 'text-green-600' : 'text-gray-400'}">{plan.progress != null && plan.progress.total > 0 ? `${plan.progress.done}/${plan.progress.total} (${Math.round((plan.progress.done / plan.progress.total) * 100)}%)` : '—'}</span>

							{#if plan.execution_claim_state === 'active'}
								<span class="shrink-0 px-1 py-0 rounded text-blue-600 bg-blue-100">실행중</span>
							{:else if plan.execution_claim_state === 'queued'}
								<span class="shrink-0 px-1 py-0 rounded text-amber-600 bg-amber-100">예약중</span>
							{/if}

							<div class="ml-auto flex shrink-0 items-center gap-1">
								<!-- Done button: canDone OR lastPlanFile -->
								{#if canDone(plan) || (isLastRun && !plan.path.includes('archive'))}
									<button
										class="shrink-0 p-1 rounded hover:bg-green-100 disabled:opacity-50"
										onclick={(e) => handleDone(e, plan)}
										disabled={doneLoadingPath === plan.path}
										title="완료 처리 (아카이브, TODO→DONE, 커밋)"
									>
										{#if doneLoadingPath === plan.path}
											<svg class="w-3.5 h-3.5 animate-spin text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" stroke-dashoffset="10"/></svg>
										{:else}
											<svg class="w-3.5 h-3.5 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
										{/if}
									</button>
								{/if}

								{#if editingPlans}
									{#if !showIgnored && !isRunning && plan.status !== '보류'}
										<button
											class="shrink-0 p-1 rounded hover:bg-yellow-100"
											onclick={(e) => handleHold(e, plan)}
											title="보류"
										>
											<svg class="w-3 h-3 text-yellow-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
										</button>
									{/if}

									{#if showIgnored && plan.status === '보류'}
										<button
											class="shrink-0 p-1 rounded hover:bg-blue-100"
											onclick={(e) => handleUnhold(e, plan)}
											title="보류 해제"
										>
											<svg class="w-3 h-3 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
										</button>
									{/if}

									{#if showIgnored}
										<button
											class="shrink-0 p-1 rounded hover:bg-gray-200"
											onclick={(e) => handleUnignore(e, plan.path)}
											title="무시 해제"
										>
											<svg class="w-3 h-3 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
										</button>
									{:else}
										<button
											class="shrink-0 p-1 rounded hover:bg-gray-200"
											onclick={(e) => handleIgnore(e, plan.path)}
											title="무시"
										>
											<svg class="w-3 h-3 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
										</button>
									{/if}

									{#if plan.path_type !== null}
										<button
											class="shrink-0 p-1 rounded hover:bg-gray-200 text-[10px] text-red-400 hover:text-red-600"
											onclick={(e) => handleRemovePath(e, plan.path)}
											title="등록 해제"
										>×</button>
									{/if}
								{/if}
							</div>
						</div>
					</div>

					{/each}
			</div>
		</div>
	{/if}
</div>
