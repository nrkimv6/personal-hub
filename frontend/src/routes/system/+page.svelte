<script lang="ts">
  import { onMount } from 'svelte';
  import { serviceDashboardApi } from '$lib/api';
  import type { ServiceDashboardStatus, NssmService, StartupProgram, ScheduledTask, WorkerProcess } from '$lib/api';

  let status = $state<ServiceDashboardStatus | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastUpdated = $state<Date | null>(null);
  let actionLoading = $state<string | null>(null);

  const REFRESH_INTERVAL = 30000;

  async function fetchStatus() {
    try {
      status = await serviceDashboardApi.status();
      error = null;
      lastUpdated = new Date();
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  });

  // === 관리 기능 ===

  async function restartService(name: string) {
    if (!confirm(`서비스 "${name}"을(를) 재시작하시겠습니까?`)) return;
    actionLoading = `nssm-restart-${name}`;
    try {
      await serviceDashboardApi.restartNssm(name);
      await fetchStatus();
    } catch (e) {
      alert(`재시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      actionLoading = null;
    }
  }

  async function stopService(name: string) {
    if (!confirm(`서비스 "${name}"을(를) 중지하시겠습니까?`)) return;
    actionLoading = `nssm-stop-${name}`;
    try {
      await serviceDashboardApi.stopNssm(name);
      await fetchStatus();
    } catch (e) {
      alert(`중지 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      actionLoading = null;
    }
  }

  async function startService(name: string) {
    actionLoading = `nssm-start-${name}`;
    try {
      await serviceDashboardApi.startNssm(name);
      await fetchStatus();
    } catch (e) {
      alert(`시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      actionLoading = null;
    }
  }

  async function removeStartup(name: string) {
    if (!confirm(`시작프로그램 "${name}"을(를) 제거하시겠습니까?`)) return;
    actionLoading = `startup-${name}`;
    try {
      await serviceDashboardApi.removeStartup(name);
      await fetchStatus();
    } catch (e) {
      alert(`제거 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      actionLoading = null;
    }
  }

  async function runTask(folder: string, name: string) {
    actionLoading = `run-${folder}-${name}`;
    try {
      await serviceDashboardApi.runTask(folder, name);
      await fetchStatus();
    } catch (e) {
      alert(`실행 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      actionLoading = null;
    }
  }

  async function removeTask(folder: string, name: string) {
    if (!confirm(`예약 작업 "${folder}/${name}"을(를) 제거하시겠습니까?\n(관리자 권한 필요)`)) return;
    actionLoading = `task-${folder}-${name}`;
    try {
      await serviceDashboardApi.removeTask(folder, name);
      await fetchStatus();
    } catch (e) {
      alert(`제거 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      actionLoading = null;
    }
  }

  async function restartWorkers() {
    if (!confirm('모든 워커를 재시작하시겠습니까?')) return;
    actionLoading = 'workers';
    try {
      await serviceDashboardApi.restartWorkers();
      await fetchStatus();
    } catch (e) {
      alert(`재시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      actionLoading = null;
    }
  }

  function formatDateTime(isoString: string | null): string {
    if (!isoString) return '-';
    try {
      const date = new Date(isoString);
      return date.toLocaleString('ko-KR', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return isoString;
    }
  }

  function getTaskResultText(result: number | null): string {
    if (result === null) return '-';
    if (result === 0) return 'OK';
    return `Error (${result})`;
  }
</script>

<svelte:head>
  <title>시스템 현황</title>
</svelte:head>

<div class="p-6 space-y-6">
  <!-- 헤더 -->
  <div class="flex justify-between items-center">
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white">시스템 현황</h1>
    <div class="flex items-center gap-4">
      {#if lastUpdated}
        <span class="text-sm text-gray-500 dark:text-gray-400">
          마지막 업데이트: {lastUpdated.toLocaleTimeString()}
        </span>
      {/if}
      <button
        onclick={fetchStatus}
        class="px-3 py-1 text-sm bg-gray-100 dark:bg-gray-700 rounded hover:bg-gray-200 dark:hover:bg-gray-600"
      >
        새로고침
      </button>
      <span class="text-xs text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
        30초 자동 새로고침
      </span>
    </div>
  </div>

  {#if loading}
    <div class="text-center py-20">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
      <p class="mt-4 text-gray-500 dark:text-gray-400">로딩 중...</p>
    </div>
  {:else if error}
    <div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
      <p class="text-red-600 dark:text-red-400 font-medium">{error}</p>
      <button
        onclick={fetchStatus}
        class="mt-3 text-sm text-red-700 dark:text-red-300 underline hover:no-underline"
      >
        다시 시도
      </button>
    </div>
  {:else if status}
    {#each Object.entries(status.projects) as [projectName, project]}
      {@const hasContent =
        project.nssm_services.length > 0 ||
        project.startup_programs.length > 0 ||
        project.scheduled_tasks.length > 0 ||
        project.worker_processes.length > 0}

      {#if hasContent}
        <div class="border dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800">
          <h2 class="text-xl font-semibold mb-4 text-blue-600 dark:text-blue-400">{projectName}</h2>

          <!-- NSSM Services -->
          {#if project.nssm_services.length > 0}
            <section class="mb-4">
              <h3 class="text-lg font-medium mb-2 text-gray-700 dark:text-gray-300">Windows 서비스</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                {#each project.nssm_services as svc}
                  <div class="p-3 rounded border flex justify-between items-center
                    {svc.status === 'Running' ? 'border-green-500 bg-green-50 dark:bg-green-900/20' : 'border-red-500 bg-red-50 dark:bg-red-900/20'}">
                    <div>
                      <div class="font-medium text-gray-900 dark:text-white">{svc.name}</div>
                      <div class="text-xs text-gray-500 dark:text-gray-400">{svc.display_name}</div>
                      <span class="px-2 py-0.5 rounded text-xs mt-1 inline-block
                        {svc.status === 'Running' ? 'bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200' : 'bg-red-200 dark:bg-red-800 text-red-800 dark:text-red-200'}">
                        {svc.status}
                      </span>
                    </div>
                    <div class="flex gap-1">
                      {#if svc.status === 'Running'}
                        <button
                          class="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
                          disabled={actionLoading?.startsWith(`nssm-`)}
                          onclick={() => restartService(svc.name)}>
                          재시작
                        </button>
                        <button
                          class="px-2 py-1 text-xs bg-orange-500 text-white rounded hover:bg-orange-600 disabled:opacity-50"
                          disabled={actionLoading?.startsWith(`nssm-`)}
                          onclick={() => stopService(svc.name)}>
                          중지
                        </button>
                      {:else}
                        <button
                          class="px-2 py-1 text-xs bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50"
                          disabled={actionLoading?.startsWith(`nssm-`)}
                          onclick={() => startService(svc.name)}>
                          시작
                        </button>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          <!-- Startup Programs -->
          {#if project.startup_programs.length > 0}
            <section class="mb-4">
              <h3 class="text-lg font-medium mb-2 text-gray-700 dark:text-gray-300">시작프로그램</h3>
              <table class="w-full text-sm">
                <thead class="bg-gray-100 dark:bg-gray-700">
                  <tr>
                    <th class="text-left p-2 text-gray-700 dark:text-gray-300">이름</th>
                    <th class="text-left p-2 text-gray-700 dark:text-gray-300">상태</th>
                    <th class="text-left p-2 text-gray-700 dark:text-gray-300">액션</th>
                  </tr>
                </thead>
                <tbody>
                  {#each project.startup_programs as prog}
                    <tr class="border-b dark:border-gray-700">
                      <td class="p-2 text-gray-900 dark:text-white">{prog.name}</td>
                      <td class="p-2">
                        <span class="text-green-600 dark:text-green-400">등록됨</span>
                      </td>
                      <td class="p-2">
                        <button
                          class="px-2 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
                          disabled={actionLoading === `startup-${prog.name}`}
                          onclick={() => removeStartup(prog.name)}>
                          제거
                        </button>
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </section>
          {/if}

          <!-- Scheduled Tasks -->
          {#if project.scheduled_tasks.length > 0}
            <section class="mb-4">
              <h3 class="text-lg font-medium mb-2 text-gray-700 dark:text-gray-300">예약 작업</h3>
              <div class="overflow-x-auto">
                <table class="w-full text-sm">
                  <thead class="bg-gray-100 dark:bg-gray-700">
                    <tr>
                      <th class="text-left p-2 text-gray-700 dark:text-gray-300">작업명</th>
                      <th class="text-left p-2 text-gray-700 dark:text-gray-300">상태</th>
                      <th class="text-left p-2 text-gray-700 dark:text-gray-300">마지막 실행</th>
                      <th class="text-left p-2 text-gray-700 dark:text-gray-300">다음 실행</th>
                      <th class="text-left p-2 text-gray-700 dark:text-gray-300">결과</th>
                      <th class="text-left p-2 text-gray-700 dark:text-gray-300">액션</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each project.scheduled_tasks as task}
                      <tr class="border-b dark:border-gray-700">
                        <td class="p-2 font-medium text-gray-900 dark:text-white" title={task.Description || ''}>
                          {task.Name}
                        </td>
                        <td class="p-2">
                          <span class="px-2 py-0.5 rounded text-xs
                            {task.State === 'Ready' ? 'bg-green-200 dark:bg-green-800 text-green-800 dark:text-green-200' : 'bg-yellow-200 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-200'}">
                            {task.State}
                          </span>
                        </td>
                        <td class="p-2 text-gray-600 dark:text-gray-400 text-xs">{formatDateTime(task.LastRun)}</td>
                        <td class="p-2 text-xs text-gray-900 dark:text-white">{formatDateTime(task.NextRun)}</td>
                        <td class="p-2 text-xs
                          {task.LastResult === 0 ? 'text-green-600 dark:text-green-400' : task.LastResult !== null ? 'text-red-600 dark:text-red-400' : 'text-gray-400'}">
                          {getTaskResultText(task.LastResult)}
                        </td>
                        <td class="p-2 space-x-1">
                          <button
                            class="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
                            disabled={actionLoading?.startsWith(`run-${task.Folder}`)}
                            onclick={() => runTask(task.Folder, task.Name)}>
                            실행
                          </button>
                          <button
                            class="px-2 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
                            disabled={actionLoading?.startsWith(`task-${task.Folder}`)}
                            onclick={() => removeTask(task.Folder, task.Name)}>
                            제거
                          </button>
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            </section>
          {/if}

          <!-- Worker Processes -->
          {#if project.worker_processes.length > 0}
            <section>
              <div class="flex justify-between items-center mb-2">
                <h3 class="text-lg font-medium text-gray-700 dark:text-gray-300">워커 프로세스</h3>
                <button
                  class="px-3 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
                  disabled={actionLoading === 'workers'}
                  onclick={restartWorkers}>
                  전체 재시작
                </button>
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                {#each project.worker_processes as worker}
                  <div class="p-3 rounded border {worker.running ? 'border-green-500 dark:border-green-600' : 'border-gray-300 dark:border-gray-600'}">
                    <div class="font-medium text-gray-900 dark:text-white">{worker.name}</div>
                    <div class="text-sm">
                      {#if worker.running}
                        <span class="text-green-600 dark:text-green-400">Running</span>
                        <span class="text-xs text-gray-500 dark:text-gray-400 ml-1">(PID: {worker.pid})</span>
                      {:else}
                        <span class="text-gray-400 dark:text-gray-500">Stopped</span>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>
            </section>
          {/if}
        </div>
      {/if}
    {/each}
  {/if}
</div>
