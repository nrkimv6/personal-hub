<script lang="ts">
	import { Button } from '$lib/components/ui';

	import { onMount } from 'svelte';
	import { schedulerApi } from '$lib/api';
	import type { ScheduledTask, TaskLog } from '$lib/types';

	let tasks = $state<ScheduledTask[]>([]);
	let logs = $state<TaskLog[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let actionLoading = $state<Record<string, boolean>>({});

	// 작업명 한글 매핑
	const taskLabels: Record<string, { name: string; description: string }> = {
		InstagramWatchdog: {
			name: 'Instagram 워커 감시',
			description: '워커 프로세스 상태 확인 및 자동 재시작'
		},
		DailyMaintenance: {
			name: '일별 유지보수',
			description: '오래된 데이터 정리 및 통계 집계'
		},
		WeeklyVacuum: {
			name: '주간 DB 최적화',
			description: '데이터베이스 VACUUM 및 인덱스 최적화'
		}
	};

	export async function fetchData() {
		loading = true;
		error = null;
		try {
			const [tasksRes, logsRes] = await Promise.all([
				schedulerApi.getTasks(),
				schedulerApi.getLogs({ limit: 20 })
			]);
			tasks = tasksRes.tasks;
			logs = logsRes.logs;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function runTask(taskName: string) {
		actionLoading[taskName] = true;
		try {
			await schedulerApi.runTask(taskName);
			alert(`${taskLabels[taskName]?.name || taskName} 작업을 실행했습니다.`);
			await fetchData();
		} catch (e) {
			alert(`실행 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
		} finally {
			actionLoading[taskName] = false;
		}
	}

	async function toggleTask(task: ScheduledTask) {
		actionLoading[task.name] = true;
		try {
			await schedulerApi.updateTask(task.name, !task.enabled);
			await fetchData();
		} catch (e) {
			alert(`상태 변경 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
		} finally {
			actionLoading[task.name] = false;
		}
	}

	function formatDateTime(dateStr: string | null): string {
		if (!dateStr) return '-';
		try {
			return new Date(dateStr).toLocaleString('ko-KR');
		} catch {
			return dateStr;
		}
	}

	function formatDuration(seconds: number | null): string {
		if (seconds === null) return '-';
		if (seconds < 60) return `${seconds}초`;
		const minutes = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return secs > 0 ? `${minutes}분 ${secs}초` : `${minutes}분`;
	}

	function getStatusColor(status: string): string {
		switch (status.toLowerCase()) {
			case 'running':
				return 'bg-primary-light text-primary';
			case 'ready':
				return 'bg-success-light text-success';
			case 'disabled':
				return 'bg-muted text-muted-foreground';
			case 'success':
				return 'bg-success-light text-success';
			case 'failed':
				return 'bg-error-light text-error';
			default:
				return 'bg-muted text-muted-foreground';
		}
	}

	function getResultIcon(result: number | null): string {
		if (result === null) return '';
		return result === 0 ? 'OK' : 'NG';
	}

	onMount(fetchData);
</script>

<div>
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else}
		<!-- 작업 목록 -->
		<div class="mb-8">
			<div class="flex items-center justify-between mb-4">
				<h3 class="text-lg font-semibold text-foreground">등록된 작업</h3>
				<Button variant="secondary" size="sm"
					onclick={() => fetchData()}
					disabled={loading}
				>
					새로고침
				</Button>
			</div>

			{#if tasks.length === 0}
				<div class="bg-warning-light border border-yellow-200 text-warning-foreground px-4 py-3 rounded-lg">
					등록된 작업이 없습니다. Windows 작업 스케줄러에서 MonitorPage 폴더에 작업을 등록해주세요.
				</div>
			{:else}
				<div class="space-y-4">
					{#each tasks as task}
						<div class="bg-white rounded-lg shadow p-4">
							<div class="flex items-start justify-between">
								<div class="flex-1">
									<div class="flex items-center gap-3 mb-2">
										<span
											class={`px-2 py-1 text-xs font-medium rounded ${task.enabled ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}`}
										>
											{task.enabled ? '활성' : '비활성'}
										</span>
										<span
											class={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(task.status)}`}
										>
											{task.status}
										</span>
										<h4 class="text-lg font-medium text-foreground">
											{taskLabels[task.name]?.name || task.name}
										</h4>
									</div>
									<p class="text-sm text-muted-foreground mb-3">
										{taskLabels[task.name]?.description || ''}
									</p>
									<div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
										<div>
											<span class="text-muted-foreground">스케줄:</span>
											<span class="ml-1 font-medium">{task.schedule || '-'}</span>
										</div>
										<div>
											<span class="text-muted-foreground">마지막 실행:</span>
											<span class="ml-1">{formatDateTime(task.last_run_time)}</span>
											{getResultIcon(task.last_result)}
										</div>
										<div>
											<span class="text-muted-foreground">다음 실행:</span>
											<span class="ml-1">{formatDateTime(task.next_run_time)}</span>
										</div>
										<div>
											<span class="text-muted-foreground">마지막 결과:</span>
											<span class="ml-1"
												>{task.last_result === null
													? '-'
													: task.last_result === 0
														? '성공'
														: `실패 (${task.last_result})`}</span
											>
										</div>
									</div>
								</div>
								<div class="flex gap-2 ml-4">
									<Button variant="primary" size="sm"
										onclick={() => runTask(task.name)}
										disabled={actionLoading[task.name]}
									>
										{actionLoading[task.name] ? '...' : '실행'}
									</Button>
									<Button
										variant={task.enabled ? 'warning' : 'success'}
										size="sm"
										onclick={() => toggleTask(task)}
										disabled={actionLoading[task.name]}
									>
										{task.enabled ? '비활성화' : '활성화'}
									</Button>
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- 실행 로그 -->
		<div>
			<h3 class="text-lg font-semibold text-foreground mb-4">최근 실행 로그</h3>

			{#if logs.length === 0}
				<div class="text-muted-foreground text-center py-8">실행 로그가 없습니다.</div>
			{:else}
				<div class="overflow-x-auto">
					<table class="min-w-full divide-y divide-border">
						<thead class="bg-background">
							<tr>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>작업</th
								>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>상태</th
								>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>시작 시간</th
								>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>소요 시간</th
								>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>처리 건수</th
								>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>오류</th
								>
							</tr>
						</thead>
						<tbody class="bg-white divide-y divide-border">
							{#each logs as log}
								<tr>
									<td class="px-4 py-3 text-sm font-medium text-foreground">
										{taskLabels[log.task_name]?.name || log.task_name}
									</td>
									<td class="px-4 py-3">
										<span
											class={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(log.status)}`}
										>
											{log.status === 'success'
												? '성공'
												: log.status === 'failed'
													? '실패'
													: log.status === 'running'
														? '실행 중'
														: log.status}
										</span>
									</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">
										{formatDateTime(log.started_at)}
									</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">
										{formatDuration(log.duration_seconds)}
									</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">
										{log.records_processed !== null
											? `${log.records_processed.toLocaleString()}건`
											: '-'}
									</td>
									<td class="px-4 py-3 text-sm text-error">
										{log.error_message || '-'}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	{/if}
</div>
