<script lang="ts">
	import { autoNextPlanApi } from '$lib/api';
	import type { AutoNextPlanFileResponse } from '$lib/api';

	interface Props {
		plans: AutoNextPlanFileResponse[];
		onPlansChange?: () => void;
		onPlanSelect?: (plan: AutoNextPlanFileResponse) => void;
		selectedPath?: string | null;
	}

	let { plans, onPlansChange, onPlanSelect, selectedPath = null }: Props = $props();

	let showIgnored = $state(false);
	let ignoredPlans = $state<AutoNextPlanFileResponse[]>([]);
	let ignoredLoading = $state(false);
	let showAddForm = $state(false);
	let externalPath = $state('');
	let addError = $state<string | null>(null);
	let addLoading = $state(false);

	async function loadIgnored() {
		ignoredLoading = true;
		try {
			ignoredPlans = await autoNextPlanApi.ignored();
		} catch (e) {
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

	async function handleAddExternal() {
		if (!externalPath.trim()) return;
		addLoading = true;
		addError = null;
		try {
			await autoNextPlanApi.addExternal(externalPath.trim());
			externalPath = '';
			showAddForm = false;
			onPlansChange?.();
		} catch (e) {
			addError = e instanceof Error ? e.message : '추가 실패';
		} finally {
			addLoading = false;
		}
	}

	async function handleRemoveExternal(path: string) {
		try {
			await autoNextPlanApi.removeExternal(path);
			onPlansChange?.();
		} catch {
			// ignore
		}
	}

	function statusBadge(status: string): string {
		const map: Record<string, string> = {
			'구현중': 'bg-blue-100 text-blue-700',
			'구현완료': 'bg-green-100 text-green-700',
			'검토완료': 'bg-purple-100 text-purple-700',
			'초안': 'bg-gray-100 text-gray-700',
			'보류': 'bg-yellow-100 text-yellow-700'
		};
		return map[status] || 'bg-gray-100 text-gray-700';
	}

	function sourceBadge(source: string): string {
		if (source === 'external') return 'bg-orange-100 text-orange-700';
		if (source === 'common') return 'bg-gray-100 text-gray-500';
		return 'bg-indigo-100 text-indigo-700';
	}

	let displayPlans = $derived(showIgnored ? ignoredPlans : plans);
</script>

<div class="bg-white rounded-lg border p-4">
	<div class="flex items-center justify-between mb-3">
		<h2 class="font-semibold">Plan 목록</h2>
		<div class="flex gap-2">
			<button
				class="text-xs px-2 py-1 rounded {showIgnored ? 'bg-gray-200 text-gray-700' : 'bg-gray-100 text-gray-500'} hover:bg-gray-200 transition-colors"
				onclick={toggleIgnored}
			>
				{showIgnored ? '활성 보기' : '무시 목록'}
			</button>
			<button
				class="text-xs px-2 py-1 rounded bg-blue-100 text-blue-700 hover:bg-blue-200 transition-colors"
				onclick={() => showAddForm = !showAddForm}
			>
				+ 외부 추가
			</button>
		</div>
	</div>

	{#if showAddForm}
		<div class="mb-3 p-3 bg-gray-50 rounded-lg space-y-2">
			{#if addError}
				<div class="text-xs text-red-600">{addError}</div>
			{/if}
			<input
				type="text"
				class="w-full border rounded px-2 py-1 text-sm"
				bind:value={externalPath}
				placeholder="Plan 파일 경로 (예: D:\work\project\...)"
			/>
			<div class="flex gap-2">
				<button
					class="text-xs px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50"
					onclick={handleAddExternal}
					disabled={addLoading || !externalPath.trim()}
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
		</div>
	{/if}

	{#if ignoredLoading}
		<div class="text-gray-400 text-sm text-center py-4">로딩 중...</div>
	{:else if displayPlans.length === 0}
		<p class="text-gray-400 text-sm">
			{showIgnored ? '무시된 Plan이 없습니다' : 'Plan 파일이 없습니다'}
		</p>
	{:else}
		<div class="space-y-2 max-h-96 overflow-y-auto">
			{#each displayPlans as plan}
				<button
					class="w-full text-left border rounded-lg p-3 hover:bg-gray-50 transition-colors {selectedPath === plan.path ? 'ring-2 ring-blue-400 bg-blue-50' : ''}"
					onclick={() => onPlanSelect?.(plan)}
				>
					<div class="flex items-center justify-between mb-1">
						<span class="text-sm font-medium truncate flex-1" title={plan.path}>{plan.filename}</span>
						<div class="flex gap-1 ml-2 shrink-0">
							<span class="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium {sourceBadge(plan.source)}">
								{plan.source}
							</span>
							<span class="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium {statusBadge(plan.status)}">
								{plan.status}
							</span>
							{#if plan.source === 'external'}
								<button
									class="text-[10px] text-red-400 hover:text-red-600 ml-1"
									onclick={() => handleRemoveExternal(plan.path)}
									title="외부 plan 제거"
								>x</button>
							{/if}
						</div>
					</div>
					<div class="flex items-center gap-2">
						<div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
							<div
								class="h-full rounded-full transition-all {plan.progress.percent >= 100 ? 'bg-green-500' : 'bg-blue-500'}"
								style="width: {plan.progress.percent}%"
							></div>
						</div>
						<span class="text-xs text-gray-500 whitespace-nowrap">
							{plan.progress.done}/{plan.progress.total} ({plan.progress.percent}%)
						</span>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>
