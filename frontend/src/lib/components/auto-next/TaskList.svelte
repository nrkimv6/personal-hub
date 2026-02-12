<script lang="ts">
	import type { AutoNextTaskResponse } from '$lib/api';

	interface Props {
		tasks: AutoNextTaskResponse[];
		total: number;
		currentFilter: string | undefined;
		onFilterChange: (filter: string | undefined) => void;
		onDelete: (id: string) => void;
		onDeleteCompleted: () => void;
	}

	let { tasks, total, currentFilter, onFilterChange, onDelete, onDeleteCompleted }: Props =
		$props();

	let expandedId = $state<string | null>(null);
	let showAll = $state(false);

	const statusFilters = [
		{ value: undefined, label: '전체' },
		{ value: 'pending', label: '대기' },
		{ value: 'running', label: '실행 중' },
		{ value: 'success', label: '성공' },
		{ value: 'failed', label: '실패' },
		{ value: 'skipped', label: '스킵' }
	];

	let filteredTasks = $derived.by(() => {
		if (showAll) return tasks;
		// "현재만" 모드: pending + running만 표시
		return tasks.filter((t) => t.status === 'pending' || t.status === 'running');
	});

	let hasCompletedTasks = $derived(
		tasks.some((t) => t.status === 'success' || t.status === 'failed' || t.status === 'skipped')
	);

	function statusBadge(status: string): string {
		const map: Record<string, string> = {
			pending: 'bg-gray-100 text-gray-700',
			running: 'bg-blue-100 text-blue-700',
			success: 'bg-green-100 text-green-700',
			failed: 'bg-red-100 text-red-700',
			skipped: 'bg-yellow-100 text-yellow-700'
		};
		return map[status] || 'bg-gray-100 text-gray-700';
	}

	function formatDate(d: string | null): string {
		if (!d) return '-';
		return new Date(d).toLocaleString('ko-KR', {
			month: '2-digit',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatDuration(sec: number | null): string {
		if (sec === null) return '-';
		if (sec < 60) return `${sec.toFixed(0)}s`;
		return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
	}

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	function handleDelete(e: Event, id: string) {
		e.stopPropagation();
		if (confirm('이 작업을 삭제하시겠습니까?')) {
			onDelete(id);
		}
	}

	function handleDeleteCompleted() {
		if (confirm('완료된 작업(성공/실패/스킵)을 모두 삭제하시겠습니까?')) {
			onDeleteCompleted();
		}
	}
</script>

<div class="bg-white rounded-lg border">
	<div class="p-4 border-b flex items-center justify-between flex-wrap gap-2">
		<div class="flex items-center gap-3">
			<h2 class="font-semibold">
				작업 목록 <span class="text-sm text-gray-400 font-normal">({showAll ? total : filteredTasks.length})</span>
			</h2>
			<!-- 현재만/전체 토글 -->
			<div class="flex rounded-lg border text-xs overflow-hidden">
				<button
					class="px-2.5 py-1 transition-colors {!showAll ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
					onclick={() => (showAll = false)}
				>
					현재만
				</button>
				<button
					class="px-2.5 py-1 transition-colors {showAll ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}"
					onclick={() => (showAll = true)}
				>
					전체 이력
				</button>
			</div>
		</div>
		<div class="flex items-center gap-2">
			{#if showAll}
				<div class="flex gap-1">
					{#each statusFilters as f}
						<button
							class="px-2.5 py-1 text-xs rounded-full border transition-colors {currentFilter === f.value ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}"
							onclick={() => onFilterChange(f.value)}
						>
							{f.label}
						</button>
					{/each}
				</div>
			{/if}
			{#if hasCompletedTasks}
				<button
					class="px-2.5 py-1 text-xs rounded-full border border-red-200 text-red-600 hover:bg-red-50 transition-colors"
					onclick={handleDeleteCompleted}
				>
					이력 정리
				</button>
			{/if}
		</div>
	</div>

	{#if filteredTasks.length === 0}
		<div class="p-8 text-center text-gray-400">
			{showAll ? '작업이 없습니다' : '진행 중인 작업이 없습니다'}
		</div>
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b text-left text-gray-500">
						<th class="px-4 py-2 font-medium">상태</th>
						<th class="px-4 py-2 font-medium">작업</th>
						<th class="px-4 py-2 font-medium hidden md:table-cell">모델</th>
						<th class="px-4 py-2 font-medium hidden md:table-cell">시간</th>
						<th class="px-4 py-2 font-medium hidden lg:table-cell">토큰</th>
						<th class="px-4 py-2 font-medium">생성일</th>
						<th class="px-4 py-2 font-medium w-10"></th>
					</tr>
				</thead>
				<tbody>
					{#each filteredTasks as task (task.id)}
						<tr
							class="border-b hover:bg-gray-50 cursor-pointer transition-colors"
							onclick={() => toggleExpand(task.id)}
						>
							<td class="px-4 py-2">
								<span
									class="inline-block px-2 py-0.5 rounded text-xs font-medium {statusBadge(task.status)}"
								>
									{task.status}
								</span>
							</td>
							<td class="px-4 py-2 max-w-xs truncate" title={task.text}>{task.text}</td>
							<td class="px-4 py-2 hidden md:table-cell text-gray-500"
								>{task.model_used || '-'}</td
							>
							<td class="px-4 py-2 hidden md:table-cell text-gray-500"
								>{formatDuration(task.duration_seconds)}</td
							>
							<td class="px-4 py-2 hidden lg:table-cell text-gray-500"
								>{task.input_tokens + task.output_tokens}</td
							>
							<td class="px-4 py-2 text-gray-500">{formatDate(task.created_at)}</td>
							<td class="px-4 py-2">
								<button
									class="text-red-400 hover:text-red-600 text-xs"
									onclick={(e) => handleDelete(e, task.id)}
									title="삭제"
								>
									삭제
								</button>
							</td>
						</tr>
						{#if expandedId === task.id}
							<tr class="bg-gray-50">
								<td colspan="7" class="px-4 py-3">
									<div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
										<div><span class="text-gray-400">ID:</span> {task.id}</div>
										<div><span class="text-gray-400">타입:</span> {task.type}</div>
										<div><span class="text-gray-400">우선순위:</span> {task.priority}</div>
										<div>
											<span class="text-gray-400">소스:</span> {task.source_path}
										</div>
										<div>
											<span class="text-gray-400">입력 토큰:</span> {task.input_tokens}
										</div>
										<div>
											<span class="text-gray-400">출력 토큰:</span> {task.output_tokens}
										</div>
										<div>
											<span class="text-gray-400">캐시(읽기):</span>
											{task.cache_read_tokens}
										</div>
										<div>
											<span class="text-gray-400">캐시(생성):</span>
											{task.cache_creation_tokens}
										</div>
										{#if task.error_message}
											<div class="col-span-full text-red-600">
												<span class="text-gray-400">에러:</span> {task.error_message}
											</div>
										{/if}
										{#if task.started_at}
											<div>
												<span class="text-gray-400">시작:</span>
												{formatDate(task.started_at)}
											</div>
										{/if}
										{#if task.finished_at}
											<div>
												<span class="text-gray-400">완료:</span>
												{formatDate(task.finished_at)}
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
