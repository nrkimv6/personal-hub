<script lang="ts">
	import { devRunnerWorkflowApi, type WorkflowResponse } from '$lib/api';

	let workflows = $state<WorkflowResponse[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let statusFilter = $state('');
	let selectedId = $state<number | null>(null);

	const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
		planned:       { label: '예정',           cls: 'bg-gray-100 text-gray-600' },
		running:       { label: '실행중',          cls: 'bg-blue-100 text-blue-700 animate-pulse' },
		merge_pending: { label: '머지 대기',       cls: 'bg-yellow-100 text-yellow-700' },
		merging:       { label: '머지중',          cls: 'bg-orange-100 text-orange-700' },
		merged:        { label: '완료',            cls: 'bg-green-100 text-green-700' },
		failed:        { label: '실패',            cls: 'bg-red-100 text-red-700' },
		cancelled:     { label: '취소',            cls: 'bg-gray-100 text-gray-400 line-through' },
	};

	async function load() {
		loading = true;
		error = null;
		try {
			workflows = await devRunnerWorkflowApi.list(statusFilter ? { status: statusFilter } : undefined);
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	}

	async function cancel(id: number, e: MouseEvent) {
		e.stopPropagation();
		try {
			const updated = await devRunnerWorkflowApi.cancel(id);
			workflows = workflows.map(w => w.id === id ? updated : w);
		} catch (err) {
			alert(`취소 실패: ${err}`);
		}
	}

	function formatDt(dt: string | null): string {
		if (!dt) return '-';
		return new Date(dt).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
	}

	$effect(() => {
		load();
	});

	// statusFilter 변경 시 재로드
	$effect(() => {
		statusFilter;
		load();
	});
</script>

<div class="flex flex-col gap-3">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<h3 class="text-sm font-semibold text-gray-700">워크플로우 이력</h3>
		<div class="flex items-center gap-2">
			<select
				bind:value={statusFilter}
				class="text-xs border border-gray-300 rounded px-2 py-1"
			>
				<option value="">전체</option>
				{#each Object.entries(STATUS_BADGE) as [val, { label }]}
					<option value={val}>{label}</option>
				{/each}
			</select>
			<button
				onclick={load}
				class="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded"
			>↻ 새로고침</button>
		</div>
	</div>

	<!-- 테이블 -->
	{#if loading}
		<div class="text-xs text-gray-400 text-center py-4">로딩 중...</div>
	{:else if error}
		<div class="text-xs text-red-500 text-center py-4">{error}</div>
	{:else if workflows.length === 0}
		<div class="text-xs text-gray-400 text-center py-4">워크플로우 없음</div>
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-xs border-collapse">
				<thead>
					<tr class="bg-gray-50 text-gray-500">
						<th class="px-2 py-1.5 text-left font-medium">슬러그</th>
						<th class="px-2 py-1.5 text-left font-medium">상태</th>
						<th class="px-2 py-1.5 text-left font-medium">엔진</th>
						<th class="px-2 py-1.5 text-left font-medium">브랜치</th>
						<th class="px-2 py-1.5 text-left font-medium">생성</th>
						<th class="px-2 py-1.5 text-left font-medium">완료</th>
						<th class="px-2 py-1.5 text-left font-medium"></th>
					</tr>
				</thead>
				<tbody>
					{#each workflows as wf}
						{@const badge = STATUS_BADGE[wf.status] ?? { label: wf.status, cls: 'bg-gray-100 text-gray-500' }}
						<tr
							class="border-t border-gray-100 hover:bg-gray-50 cursor-pointer {selectedId === wf.id ? 'bg-blue-50' : ''}"
							onclick={() => selectedId = selectedId === wf.id ? null : wf.id}
						>
							<td class="px-2 py-1.5 font-mono truncate max-w-[180px]" title={wf.slug}>{wf.slug}</td>
							<td class="px-2 py-1.5">
								<span class="px-1.5 py-0.5 rounded text-[10px] font-medium {badge.cls}">{badge.label}</span>
							</td>
							<td class="px-2 py-1.5 text-gray-500">{wf.engine ?? '-'}</td>
							<td class="px-2 py-1.5 font-mono text-gray-500 truncate max-w-[120px]" title={wf.branch ?? ''}>{wf.branch ?? '-'}</td>
							<td class="px-2 py-1.5 text-gray-400 whitespace-nowrap">{formatDt(wf.created_at)}</td>
							<td class="px-2 py-1.5 text-gray-400 whitespace-nowrap">{formatDt(wf.finished_at)}</td>
							<td class="px-2 py-1.5">
								{#if wf.status === 'planned' || wf.status === 'running'}
									<button
										onclick={(e) => cancel(wf.id, e)}
										class="text-[10px] px-1.5 py-0.5 bg-red-50 text-red-500 hover:bg-red-100 rounded"
									>취소</button>
								{/if}
							</td>
						</tr>
						<!-- 상세 행 -->
						{#if selectedId === wf.id}
							<tr class="bg-blue-50 border-t border-blue-100">
								<td colspan="7" class="px-3 py-2">
									<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
										{#if wf.plan_file}
											<div><span class="text-gray-500">계획서:</span> <span class="font-mono">{wf.plan_file}</span></div>
										{/if}
										{#if wf.runner_id}
											<div><span class="text-gray-500">runner_id:</span> <span class="font-mono">{wf.runner_id}</span></div>
										{/if}
										{#if wf.worktree_path}
											<div><span class="text-gray-500">worktree:</span> <span class="font-mono truncate">{wf.worktree_path}</span></div>
										{/if}
										{#if wf.commit_hash}
											<div><span class="text-gray-500">커밋:</span> <span class="font-mono">{wf.commit_hash.slice(0, 8)}</span></div>
										{/if}
										{#if wf.started_at}
											<div><span class="text-gray-500">시작:</span> {formatDt(wf.started_at)}</div>
										{/if}
										{#if wf.merged_at}
											<div><span class="text-gray-500">머지:</span> {formatDt(wf.merged_at)}</div>
										{/if}
										{#if wf.error_message}
											<div class="col-span-2 text-red-600 bg-red-50 px-2 py-1 rounded">
												<span class="text-gray-500">오류:</span> {wf.error_message.slice(0, 300)}
											</div>
										{/if}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
