<script lang="ts">
	import { onMount } from 'svelte';
	import { schedulerApi } from '$lib/api';
	import type { TaskLog } from '$lib/types';
	import { RefreshCw, CheckCircle, XCircle, Clock, AlertCircle } from 'lucide-svelte';

	let logs = $state<TaskLog[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let selectedTask = $state('');
	let taskNames = $state<string[]>([]);

	async function fetchLogs(silent = false) {
		try {
			if (!silent) loading = true;
			error = null;
			const params: { task_name?: string; limit?: number } = { limit: 100 };
			if (selectedTask) params.task_name = selectedTask;
			const result = await schedulerApi.getLogs(params);
			logs = result.logs;
			// 태스크 이름 목록 추출
			if (!selectedTask) {
				const names = [...new Set(result.logs.map((l) => l.task_name))].sort();
				taskNames = names;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '실행 이력을 불러오지 못했습니다';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchLogs();
	});

	function formatDuration(seconds: number | null): string {
		if (seconds === null) return '-';
		if (seconds < 60) return `${seconds.toFixed(1)}초`;
		const m = Math.floor(seconds / 60);
		const s = Math.floor(seconds % 60);
		return `${m}분 ${s}초`;
	}

	function formatDatetime(dt: string | null): string {
		if (!dt) return '-';
		const d = new Date(dt);
		return d.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	function getStatusColor(status: string): string {
		switch (status) {
			case 'success': return 'text-green-600 dark:text-green-400';
			case 'failed': return 'text-red-600 dark:text-red-400';
			case 'running': return 'text-blue-600 dark:text-blue-400';
			default: return 'text-muted-foreground';
		}
	}
</script>

<div class="p-6">
	<div class="flex items-center justify-between mb-4">
		<h2 class="text-lg font-semibold dark:text-white">실행 이력</h2>
		<div class="flex items-center gap-2">
			<select
				bind:value={selectedTask}
				onchange={() => fetchLogs()}
				class="text-sm border border-border rounded px-2 py-1 bg-background dark:text-white"
			>
				<option value="">전체 태스크</option>
				{#each taskNames as name}
					<option value={name}>{name}</option>
				{/each}
			</select>
			<button
				onclick={() => fetchLogs()}
				class="p-1.5 rounded hover:bg-muted transition-colors"
				title="새로고침"
			>
				<RefreshCw class="w-4 h-4 text-muted-foreground" />
			</button>
		</div>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-12 text-muted-foreground">
			<Clock class="w-5 h-5 animate-spin mr-2" />
			불러오는 중...
		</div>
	{:else if error}
		<div class="flex items-center gap-2 text-red-600 dark:text-red-400 py-6">
			<AlertCircle class="w-5 h-5 shrink-0" />
			{error}
		</div>
	{:else if logs.length === 0}
		<div class="text-center py-12 text-muted-foreground text-sm">실행 이력이 없습니다</div>
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-border text-left text-muted-foreground">
						<th class="pb-2 pr-4 font-medium">태스크</th>
						<th class="pb-2 pr-4 font-medium">상태</th>
						<th class="pb-2 pr-4 font-medium">시작</th>
						<th class="pb-2 pr-4 font-medium">완료</th>
						<th class="pb-2 pr-4 font-medium">소요</th>
						<th class="pb-2 font-medium">오류</th>
					</tr>
				</thead>
				<tbody>
					{#each logs as log}
						<tr class="border-b border-border/50 hover:bg-muted/20 transition-colors">
							<td class="py-2 pr-4 font-mono text-xs">{log.task_name}</td>
							<td class="py-2 pr-4">
								<span class="flex items-center gap-1 {getStatusColor(log.status)}">
									{#if log.status === 'success'}
										<CheckCircle class="w-3.5 h-3.5" />
									{:else if log.status === 'failed'}
										<XCircle class="w-3.5 h-3.5" />
									{:else}
										<Clock class="w-3.5 h-3.5 animate-spin" />
									{/if}
									{log.status}
								</span>
							</td>
							<td class="py-2 pr-4 text-muted-foreground">{formatDatetime(log.started_at)}</td>
							<td class="py-2 pr-4 text-muted-foreground">{formatDatetime(log.finished_at)}</td>
							<td class="py-2 pr-4">{formatDuration(log.duration_seconds)}</td>
							<td class="py-2 text-red-500 text-xs max-w-xs truncate" title={log.error_message ?? ''}>
								{log.error_message ?? ''}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
