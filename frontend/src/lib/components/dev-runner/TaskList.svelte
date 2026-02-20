<script lang="ts">
	import type { DevRunnerTaskResponse } from '$lib/api';

	interface Props {
		tasks: DevRunnerTaskResponse[];
		total: number;
		currentFilter: string | undefined;
		onFilterChange: (filter: string | undefined) => void;
		onDelete: (id: string) => void;
		onDeleteCompleted: () => void;
		onDeleteOld?: (hours: number) => void;
	}

	let { tasks, total, currentFilter, onFilterChange, onDelete, onDeleteCompleted, onDeleteOld }: Props =
		$props();

	let expandedId = $state<string | null>(null);

	const statusFilters = [
		{ value: undefined, label: 'all' },
		{ value: 'pending', label: 'pending' },
		{ value: 'running', label: 'running' },
		{ value: 'success', label: 'success' },
		{ value: 'failed', label: 'failed' },
		{ value: 'skipped', label: 'skipped' }
	];

	let hasCompletedTasks = $derived(
		tasks.some((t) => t.status === 'success' || t.status === 'failed' || t.status === 'skipped')
	);

	// 자동 정리
	let autoCleanup = $state(
		typeof window !== 'undefined'
			? localStorage.getItem('devRunner_autoCleanup') === 'true'
			: false
	);
	let autoCleanupHours = $state(
		typeof window !== 'undefined'
			? parseInt(localStorage.getItem('devRunner_autoCleanupHours') || '24')
			: 24
	);

	$effect(() => {
		if (typeof window !== 'undefined') {
			localStorage.setItem('devRunner_autoCleanup', String(autoCleanup));
			localStorage.setItem('devRunner_autoCleanupHours', String(autoCleanupHours));
		}
	});

	$effect(() => {
		if (!autoCleanup || !onDeleteOld) return;
		onDeleteOld(autoCleanupHours);
		const interval = setInterval(() => onDeleteOld!(autoCleanupHours), 3600000);
		return () => clearInterval(interval);
	});

	function statusConfig(status: string): { label: string; className: string } {
		const map: Record<string, { label: string; className: string }> = {
			pending: { label: 'Pending', className: 'bg-gray-100 text-gray-600' },
			running: { label: 'Running', className: 'bg-blue-100 text-blue-700 border border-blue-200' },
			success: { label: 'Success', className: 'bg-green-100 text-green-700 border border-green-200' },
			failed: { label: 'Failed', className: 'bg-red-100 text-red-700 border border-red-200' },
			skipped: { label: 'Skipped', className: 'bg-gray-200 text-gray-600 border border-gray-300' }
		};
		return map[status] || map.pending;
	}

	function formatDate(d: string | null): string {
		if (!d) return '-';
		return new Date(d).toLocaleTimeString('ko-KR', {
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
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

	function countByStatus(status: string): number {
		return tasks.filter(t => t.status === status).length;
	}

	// Phase 3: running 항목 최상위 + 최신순 정렬
	let sortedTasks = $derived(
		[...tasks].sort((a, b) => {
			if (a.status === 'running' && b.status !== 'running') return -1;
			if (a.status !== 'running' && b.status === 'running') return 1;
			// 최신이 위 (started_at 내림차순)
			const aTime = a.started_at ? new Date(a.started_at).getTime() : 0;
			const bTime = b.started_at ? new Date(b.started_at).getTime() : 0;
			return bTime - aTime;
		})
	);
</script>

<div class="flex flex-col gap-3 h-full">
	<!-- Filter Bar -->
	<div class="flex items-center justify-between flex-wrap gap-2">
		<div class="flex items-center gap-1">
			{#each statusFilters as f}
				<button
					class="h-6 px-2 text-[10px] rounded capitalize transition-colors {currentFilter === f.value ? 'bg-gray-100 font-medium' : 'text-gray-400 hover:text-gray-600'}"
					onclick={() => onFilterChange(f.value)}
				>
					{f.label}
					{#if f.value !== undefined}
						<span class="ml-1 font-mono">{countByStatus(f.value)}</span>
					{/if}
				</button>
			{/each}
		</div>

		<div class="flex items-center gap-3">
			{#if hasCompletedTasks}
				<button
					class="h-6 px-2 text-[10px] text-gray-500 hover:text-red-600 transition-colors inline-flex items-center gap-1"
					onclick={handleDeleteCompleted}
				>
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
					Clear Done
				</button>
			{/if}

			<div class="flex items-center gap-1.5">
				<label class="relative inline-flex items-center cursor-pointer">
					<input type="checkbox" bind:checked={autoCleanup} class="sr-only peer" />
					<div class="w-7 h-3.5 bg-gray-200 rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[1px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-2.5 after:w-2.5 after:transition-all peer-checked:bg-blue-500"></div>
				</label>
				<span class="text-[10px] text-gray-500">Auto</span>
				{#if autoCleanup}
					<select
						bind:value={autoCleanupHours}
						class="text-[10px] h-6 w-[60px] border rounded px-1"
					>
						<option value={12}>12h</option>
						<option value={24}>24h</option>
						<option value={48}>48h</option>
						<option value={72}>72h</option>
						<option value={168}>7d</option>
					</select>
				{/if}
			</div>
		</div>
	</div>

	<!-- Task List (card style) -->
	<div class="flex-1 overflow-y-auto">
		{#if sortedTasks.length === 0}
			<div class="text-center py-8 text-sm text-gray-400">
				No tasks matching filter
			</div>
		{:else}
			<div class="flex flex-col gap-1.5 pr-2">
				{#each sortedTasks as task (task.id)}
					<div class="border rounded-md overflow-hidden {task.status === 'running' ? 'border-l-2 border-l-blue-500 bg-blue-50/50' : ''}">
						<!-- Collapsed row -->
						<button
							onclick={() => toggleExpand(task.id)}
							class="flex items-center gap-3 w-full px-3 py-2.5 hover:bg-gray-50 transition-colors text-left"
						>
							<span class="text-[10px] px-1.5 py-0 h-4 inline-flex items-center rounded shrink-0 {statusConfig(task.status).className}">
								{statusConfig(task.status).label}
							</span>
							{#if task.source_path}
								<span class="text-xs text-gray-500 font-mono shrink-0 w-[130px] truncate">
									{task.source_path.split(/[\\/]/).pop()}
								</span>
							{/if}
							<span class="text-xs truncate flex-1 min-w-0">{task.text}</span>
							<div class="flex items-center gap-3 shrink-0 text-xs text-gray-500">
								{#if task.duration_seconds !== null}
									<span class="font-mono tabular-nums">{formatDuration(task.duration_seconds)}</span>
								{/if}
								{#if task.input_tokens > 0}
									<span class="font-mono tabular-nums hidden lg:inline">
										{(task.input_tokens / 1000).toFixed(1)}k
									</span>
								{/if}
								<svg
									class="w-3.5 h-3.5 transition-transform {expandedId === task.id ? 'rotate-180' : ''}"
									viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
								>
									<path d="M6 9l6 6 6-6" />
								</svg>
							</div>
						</button>

						<!-- Expanded detail -->
						{#if expandedId === task.id}
							<div class="border-t bg-gray-50 px-3 py-3 flex flex-col gap-2">
								<p class="text-xs leading-relaxed">{task.text}</p>

								<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
									<span>Model: <span class="font-mono">{task.model_used || '-'}</span></span>
									{#if task.started_at}
										<span>Started: <span class="font-mono">{formatDate(task.started_at)}</span></span>
									{/if}
									{#if task.finished_at}
										<span>Completed: <span class="font-mono">{formatDate(task.finished_at)}</span></span>
									{/if}
									<span>
										Tokens: <span class="font-mono">{task.input_tokens.toLocaleString()} in / {task.output_tokens.toLocaleString()} out / {task.cache_read_tokens.toLocaleString()} cached</span>
									</span>
								</div>

								{#if task.error_message}
									<div class="flex items-start gap-2 rounded-md bg-red-50 border border-red-200 p-2.5 mt-1">
										<svg class="w-3.5 h-3.5 text-red-500 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
										<p class="text-xs text-red-600 leading-relaxed">{task.error_message}</p>
									</div>
								{/if}

								<div class="flex justify-end mt-1">
									<button
										class="h-6 px-2 text-xs text-gray-400 hover:text-red-500 transition-colors inline-flex items-center gap-1"
										onclick={(e) => handleDelete(e, task.id)}
									>
										<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
										삭제
									</button>
								</div>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
