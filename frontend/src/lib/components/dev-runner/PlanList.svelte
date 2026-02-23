<script lang="ts">
	import { devRunnerPlanApi } from '$lib/api';
	import type { DevRunnerPlanFileResponse, DevRunnerPlanDetailResponse, DevRunnerRegisteredPathResponse } from '$lib/api';
	import { encodePathToBase64 } from '$lib/utils/encoding';

	let doneLoadingPath = $state<string | null>(null);
	let doneMessage = $state<{ path: string; success: boolean; text: string; remaining?: number; total?: number; planStatus?: string } | null>(null);

	async function handleDone(e: Event, plan: DevRunnerPlanFileResponse) {
		e.stopPropagation();
		if (!confirm('완료 처리를 실행하시겠습니까?\n아카이브 이동, TODO→DONE, 커밋이 수행됩니다.')) return;
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
		} catch (err) {
			doneMessage = { path: plan.path, success: false, text: err instanceof Error ? err.message : '완료 처리 실패' };
		} finally {
			doneLoadingPath = null;
		}
	}

	function canDone(plan: DevRunnerPlanFileResponse): boolean {
		if (plan.path.includes('archive')) return false;
		return (plan.progress.total > 0 && plan.progress.done === plan.progress.total)
			|| plan.status === '구현완료';
	}

	interface Props {
		plans: DevRunnerPlanFileResponse[];
		onPlansChange?: () => void;
		runningPlanFile?: string | null;
		onPlanSelect?: (path: string) => void;
	}

	let { plans, onPlansChange, runningPlanFile = null, onPlanSelect }: Props = $props();

	let showIgnored = $state(false);
	let ignoredPlans = $state<DevRunnerPlanFileResponse[]>([]);
	let ignoredLoading = $state(false);
	let showAddForm = $state(false);
	let newPath = $state('');
	let addError = $state<string | null>(null);
	let addLoading = $state(false);

	// 등록된 경로 목록
	let registeredPaths = $state<DevRunnerRegisteredPathResponse[]>([]);
	let registeredPathsLoading = $state(false);

	// Plan detail (inline accordion)
	let selectedPath = $state<string | null>(null);
	let planDetail = $state<DevRunnerPlanDetailResponse | null>(null);
	let planDetailLoading = $state(false);
	// Phase accordion state
	let openPhases = $state<Set<number>>(new Set());

	async function handlePlanSelect(plan: DevRunnerPlanFileResponse) {
		if (selectedPath === plan.path) {
			selectedPath = null;
			planDetail = null;
			openPhases = new Set();
			return;
		}
		selectedPath = plan.path;
		onPlanSelect?.(plan.path);
		planDetailLoading = true;
		planDetail = null;
		openPhases = new Set();
		try {
			const encoded = encodePathToBase64(plan.path);
			planDetail = await devRunnerPlanApi.items(encoded);
		} catch {
			planDetail = null;
		} finally {
			planDetailLoading = false;
		}
	}

	function togglePhase(index: number) {
		const next = new Set(openPhases);
		if (next.has(index)) {
			next.delete(index);
		} else {
			next.add(index);
		}
		openPhases = next;
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
			await devRunnerPlanApi.addPath(newPath.trim());
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
			'초안': 'bg-gray-100 text-gray-600',
			'보류': 'bg-yellow-100 text-yellow-700 border border-yellow-200'
		};
		return map[status] || 'bg-gray-100 text-gray-600';
	}

	let displayPlans = $derived(showIgnored ? ignoredPlans : (plans ?? []));
</script>

<div class="flex flex-col gap-3 min-h-0 flex-1">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<span class="text-xs text-gray-500 font-medium uppercase tracking-wider">Plan Files</span>
		<div class="flex gap-1">
			{#if selectedPath}
				<button
					class="h-6 px-2 text-[10px] rounded text-gray-500 hover:bg-gray-100 transition-colors"
					onclick={() => { selectedPath = null; planDetail = null; openPhases = new Set(); }}
					title="모두 접기"
				>
					접기
				</button>
			{/if}
			<button
				class="h-6 px-2 text-[10px] rounded text-gray-500 hover:bg-gray-100 transition-colors"
				onclick={toggleIgnored}
			>
				{showIgnored ? '활성 보기' : '무시 목록'}
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
				<button
					class="text-xs px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
					onclick={handleAddPath}
					disabled={addLoading || !newPath.trim()}
				>
					{addLoading ? '추가 중...' : '추가'}
				</button>
				<button
					class="text-xs px-3 py-1 rounded bg-gray-200 text-gray-600 hover:bg-gray-300"
					onclick={() => { showAddForm = false; addError = null; }}
				>
					취소
				</button>
			</div>

		<!-- 등록된 경로 목록 -->
		{#if registeredPathsLoading}
			<div class="text-[10px] text-gray-400">로딩 중...</div>
		{:else if registeredPaths.length > 0}
			<div class="border-t pt-2 mt-1 space-y-1 max-h-40 overflow-y-auto">
				<div class="text-[10px] text-gray-400 font-medium uppercase tracking-wider">등록된 경로</div>
				{#each registeredPaths as ep}
					<div class="flex items-center gap-1.5 text-[10px]">
						<!-- 파일/폴더 아이콘 -->
						{#if ep.type === 'folder'}
							<svg class="w-3 h-3 shrink-0 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
						{:else}
							<svg class="w-3 h-3 shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
						{/if}
						<span class="truncate flex-1 text-gray-600" title={ep.path}>{ep.path}</span>
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
					{@const isRunning = runningPlanFile === plan.path}
					{@const isSelected = selectedPath === plan.path}
					<button
						onclick={() => handlePlanSelect(plan)}
						class="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left transition-colors w-full
							{isRunning ? 'border border-green-300 bg-green-50' : isSelected ? 'bg-blue-50' : 'hover:bg-gray-50'}"
					>
						<!-- Running indicator dot -->
						{#if isRunning}
							<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse shrink-0"></span>
						{:else if plan.path_type === 'folder'}
							<svg class="w-3.5 h-3.5 shrink-0 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
						{:else}
							<svg class="w-3.5 h-3.5 shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
						{/if}

						<!-- Compact 1-line: filename + done/total -->
						<span class="text-xs font-medium truncate flex-1 min-w-0 {isRunning ? 'text-green-800' : ''}">{plan.filename}</span>
						<span class="text-[10px] font-mono shrink-0 {isRunning ? 'text-green-600' : 'text-gray-400'}">{plan.progress.done}/{plan.progress.total}</span>

						<!-- Eye/EyeOff toggle -->
						{#if canDone(plan)}
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
					</button>

					<!-- Plan Detail (inline accordion) -->
					{#if selectedPath === plan.path}
						<div class="border-t pt-3 mt-1 ml-6">
							{#if planDetailLoading}
								<div class="flex items-center justify-center py-4">
									<div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
								</div>
							{:else if planDetail}
								<div class="max-h-48 overflow-y-auto">
									{#each planDetail.phases as phase, i}
										<div class="mb-1">
											<!-- Phase trigger -->
											<button
												class="py-2 text-xs text-gray-500 hover:text-gray-700 w-full text-left flex items-center gap-1"
												onclick={() => togglePhase(i)}
											>
												<svg
													class="w-3 h-3 transition-transform {openPhases.has(i) ? 'rotate-90' : ''}"
													viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
												>
													<path d="M9 18l6-6-6-6" />
												</svg>
												{phase.name}
											</button>

											<!-- Phase content -->
											{#if openPhases.has(i)}
												<div class="flex flex-col gap-1.5 pl-4 pb-2">
													{#each phase.items as item}
														<div class="flex items-start gap-2 text-xs">
															{#if item.checked}
																<svg class="w-3.5 h-3.5 shrink-0 text-green-500 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
															{:else}
																<svg class="w-3.5 h-3.5 shrink-0 text-gray-400 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>
															{/if}
															<span class="{item.checked ? 'text-gray-400 line-through' : ''}">{item.text}</span>
														</div>
														{#each item.children as child}
															<div class="flex items-start gap-2 text-xs ml-4">
																{#if child.checked}
																	<svg class="w-3.5 h-3.5 shrink-0 text-green-500 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
																{:else}
																	<svg class="w-3.5 h-3.5 shrink-0 text-gray-400 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>
																{/if}
																<span class="{child.checked ? 'text-gray-400 line-through' : ''}">{child.text}</span>
															</div>
														{/each}
													{/each}
												</div>
											{/if}
										</div>
									{/each}
								</div>
							{:else}
								<div class="text-xs text-gray-400 py-2 text-center">상세 정보를 불러올 수 없습니다</div>
							{/if}
						</div>
					{/if}
				{/each}
			</div>
		</div>
	{/if}
</div>
