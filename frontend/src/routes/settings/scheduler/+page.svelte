<script lang="ts">
  import { onMount } from 'svelte';
  import { schedulerApi } from '$lib/api';
  import type { ScheduledTask, TaskLog } from '$lib/types';

  let tasks: ScheduledTask[] = [];
  let logs: TaskLog[] = [];
  let loading = true;
  let error: string | null = null;
  let actionLoading: Record<string, boolean> = {};

  // 작업명 한글 매핑
  const taskLabels: Record<string, { name: string; description: string }> = {
    'InstagramWatchdog': {
      name: 'Instagram 워커 감시',
      description: '워커 프로세스 상태 확인 및 자동 재시작'
    },
    'DailyMaintenance': {
      name: '일별 유지보수',
      description: '오래된 데이터 정리 및 통계 집계'
    },
    'WeeklyVacuum': {
      name: '주간 DB 최적화',
      description: '데이터베이스 VACUUM 및 인덱스 최적화'
    }
  };

  async function fetchData() {
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
        return 'bg-blue-100 text-blue-800';
      case 'ready':
        return 'bg-green-100 text-green-800';
      case 'disabled':
        return 'bg-gray-100 text-gray-600';
      case 'success':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-600';
    }
  }

  function getResultIcon(result: number | null): string {
    if (result === null) return '';
    return result === 0 ? '✅' : '❌';
  }

  onMount(fetchData);
</script>

<div class="p-6">
  <div class="mb-6 flex items-center justify-between">
    <div>
      <h2 class="text-2xl font-bold text-gray-900">스케줄 작업 관리</h2>
      <p class="text-sm text-gray-500 mt-1">Windows 작업 스케줄러에 등록된 작업을 관리합니다</p>
    </div>
    <button
      class="btn btn-secondary"
      on:click={fetchData}
      disabled={loading}
    >
      {loading ? '로딩...' : '새로고침'}
    </button>
  </div>

  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else}
    <!-- 작업 목록 -->
    <div class="mb-8">
      <h3 class="text-lg font-semibold text-gray-900 mb-4">등록된 작업</h3>

      {#if tasks.length === 0}
        <div class="bg-yellow-50 border border-yellow-200 text-yellow-700 px-4 py-3 rounded-lg">
          등록된 작업이 없습니다. Windows 작업 스케줄러에서 MonitorPage 폴더에 작업을 등록해주세요.
        </div>
      {:else}
        <div class="space-y-4">
          {#each tasks as task}
            <div class="card">
              <div class="flex items-start justify-between">
                <div class="flex-1">
                  <div class="flex items-center gap-3 mb-2">
                    <span class={`px-2 py-1 text-xs font-medium rounded ${task.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                      {task.enabled ? '활성' : '비활성'}
                    </span>
                    <span class={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(task.status)}`}>
                      {task.status}
                    </span>
                    <h4 class="text-lg font-medium text-gray-900">
                      {taskLabels[task.name]?.name || task.name}
                    </h4>
                  </div>
                  <p class="text-sm text-gray-500 mb-3">
                    {taskLabels[task.name]?.description || ''}
                  </p>
                  <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <span class="text-gray-500">스케줄:</span>
                      <span class="ml-1 font-medium">{task.schedule || '-'}</span>
                    </div>
                    <div>
                      <span class="text-gray-500">마지막 실행:</span>
                      <span class="ml-1">{formatDateTime(task.last_run_time)}</span>
                      {getResultIcon(task.last_result)}
                    </div>
                    <div>
                      <span class="text-gray-500">다음 실행:</span>
                      <span class="ml-1">{formatDateTime(task.next_run_time)}</span>
                    </div>
                    <div>
                      <span class="text-gray-500">마지막 결과:</span>
                      <span class="ml-1">{task.last_result === null ? '-' : task.last_result === 0 ? '성공' : `실패 (${task.last_result})`}</span>
                    </div>
                  </div>
                </div>
                <div class="flex gap-2 ml-4">
                  <button
                    class="btn btn-sm btn-primary"
                    on:click={() => runTask(task.name)}
                    disabled={actionLoading[task.name]}
                  >
                    {actionLoading[task.name] ? '...' : '실행'}
                  </button>
                  <button
                    class="btn btn-sm {task.enabled ? 'btn-warning' : 'btn-success'}"
                    on:click={() => toggleTask(task)}
                    disabled={actionLoading[task.name]}
                  >
                    {task.enabled ? '비활성화' : '활성화'}
                  </button>
                </div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </div>

    <!-- 실행 로그 -->
    <div>
      <h3 class="text-lg font-semibold text-gray-900 mb-4">최근 실행 로그</h3>

      {#if logs.length === 0}
        <div class="text-gray-500 text-center py-8">
          실행 로그가 없습니다.
        </div>
      {:else}
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">작업</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">시작 시간</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">소요 시간</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">처리 건수</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">오류</th>
              </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
              {#each logs as log}
                <tr>
                  <td class="px-4 py-3 text-sm font-medium text-gray-900">
                    {taskLabels[log.task_name]?.name || log.task_name}
                  </td>
                  <td class="px-4 py-3">
                    <span class={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(log.status)}`}>
                      {log.status === 'success' ? '성공' : log.status === 'failed' ? '실패' : log.status === 'running' ? '실행 중' : log.status}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-sm text-gray-500">
                    {formatDateTime(log.started_at)}
                  </td>
                  <td class="px-4 py-3 text-sm text-gray-500">
                    {formatDuration(log.duration_seconds)}
                  </td>
                  <td class="px-4 py-3 text-sm text-gray-500">
                    {log.records_processed !== null ? `${log.records_processed.toLocaleString()}건` : '-'}
                  </td>
                  <td class="px-4 py-3 text-sm text-red-600">
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

<style>
  .btn {
    @apply inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg transition-colors;
  }
  .btn-sm {
    @apply px-3 py-1.5 text-xs;
  }
  .btn-primary {
    @apply bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50;
  }
  .btn-secondary {
    @apply bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50;
  }
  .btn-success {
    @apply bg-green-600 text-white hover:bg-green-700 disabled:opacity-50;
  }
  .btn-warning {
    @apply bg-yellow-500 text-white hover:bg-yellow-600 disabled:opacity-50;
  }
  .card {
    @apply bg-white rounded-lg shadow p-4;
  }
</style>
