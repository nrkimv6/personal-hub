<script lang="ts">
  import { onMount } from 'svelte';
  import { serviceDashboardApi, systemApi } from '$lib/api';
  import type { ServiceDashboardStatus } from '$lib/api';

  // Props
  interface Props {
    onStatusChange?: (runningCount: number, totalCount: number) => void;
  }
  let { onStatusChange }: Props = $props();

  let status = $state<ServiceDashboardStatus | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state<string | null>(null);
  let refreshing = $state(false);

  // Self-restart 상태
  let selfRestartState = $state<'idle' | 'requested' | 'waiting' | 'checking' | 'done' | 'failed'>('idle');
  let selfRestartMessage = $state('');

  const REFRESH_INTERVAL = 30000;

  // 서버 수집 시각을 상대 시간으로 포맷
  function formatCollectedAt(isoString: string | null): string {
    if (!isoString) return '수집 전';
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diffSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

      if (diffSeconds < 10) return '방금 전';
      if (diffSeconds < 60) return `${diffSeconds}초 전`;
      if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}분 전`;
      return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  }

  async function fetchStatus() {
    try {
      status = await serviceDashboardApi.status();
      error = null;
      updateServiceCounts();
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  // 즉시 수집 (서버에서 PowerShell 실행)
  async function refreshStatus() {
    if (refreshing) return;
    refreshing = true;
    try {
      status = await serviceDashboardApi.refresh();
      error = null;
      updateServiceCounts();
    } catch (e) {
      error = e instanceof Error ? e.message : '새로고침 실패';
    } finally {
      refreshing = false;
    }
  }

  // 서비스 상태 카운트 계산 (부모 컴포넌트에 전달)
  function updateServiceCounts() {
    if (status && onStatusChange) {
      let running = 0;
      let total = 0;
      for (const project of Object.values(status.projects)) {
        for (const svc of project.nssm_services) {
          total++;
          if (svc.status === 'Running') running++;
        }
      }
      onStatusChange(running, total);
    }
  }

  onMount(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  });

  // === 관리 기능 ===

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
    if (!confirm('워커 프로세스를 재시작하시겠습니까?\n(watchdog가 자동으로 재시작합니다)')) return;
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

  async function selfRestartApi() {
    if (!confirm('API 서버를 graceful 재시작하시겠습니까?\n\n소켓을 정상 해제한 후 NSSM이 자동으로 재시작합니다.\n(약 15초 소요)')) return;

    selfRestartState = 'requested';
    selfRestartMessage = 'Self-restart 요청 중...';

    try {
      const response = await systemApi.selfRestart(2.0);
      selfRestartState = 'waiting';
      selfRestartMessage = `PID ${response.pid} 종료 대기 중... (NSSM이 자동 재시작)`;

      // shutdown(2초) + NSSM throttle(10초) + startup(~3초) 대기
      await new Promise(r => setTimeout(r, 15000));

      // Health check 반복
      selfRestartState = 'checking';
      selfRestartMessage = 'API 재시작 확인 중...';

      const maxRetries = 6;
      const retryInterval = 5000;
      let success = false;

      for (let i = 1; i <= maxRetries; i++) {
        try {
          await systemApi.status();
          success = true;
          break;
        } catch {
          selfRestartMessage = `API 응답 대기 중... (${i}/${maxRetries})`;
          if (i < maxRetries) await new Promise(r => setTimeout(r, retryInterval));
        }
      }

      if (success) {
        selfRestartState = 'done';
        selfRestartMessage = 'API 재시작 완료';
        await fetchStatus();
        // 3초 후 상태 초기화
        setTimeout(() => {
          selfRestartState = 'idle';
          selfRestartMessage = '';
        }, 3000);
      } else {
        selfRestartState = 'failed';
        selfRestartMessage = 'API 재시작 확인 실패. 수동 확인 필요.';
      }
    } catch (e) {
      selfRestartState = 'failed';
      selfRestartMessage = `요청 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`;
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

<div class="space-y-6">
  <!-- 헤더 -->
  <div class="flex justify-between items-center">
    <div class="flex items-center gap-4">
      <!-- 서버 수집 시각 표시 -->
      <span class="text-sm text-muted-foreground dark:text-muted-foreground">
        마지막 수집: {formatCollectedAt(status?.collected_at ?? null)}
      </span>

      <!-- 즉시 수집 버튼 -->
      <button
        onclick={refreshStatus}
        disabled={refreshing}
        class="px-3 py-1 text-sm bg-primary text-white rounded hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {refreshing ? '수집 중...' : '즉시 수집'}
      </button>

      <!-- 캐시 새로고침 버튼 -->
      <button
        onclick={fetchStatus}
        class="px-3 py-1 text-sm bg-muted dark:bg-gray-700 rounded hover:bg-secondary dark:hover:bg-gray-600"
      >
        새로고침
      </button>

      <span class="text-xs text-muted-foreground dark:text-muted-foreground bg-muted dark:bg-gray-800 px-2 py-1 rounded">
        30초 자동
      </span>
    </div>
  </div>

  {#if loading}
    <div class="text-center py-20">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
      <p class="mt-4 text-muted-foreground dark:text-muted-foreground">로딩 중...</p>
    </div>
  {:else if error}
    <div class="bg-error-light dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
      <p class="text-error dark:text-red-400 font-medium">{error}</p>
      <button
        onclick={fetchStatus}
        class="mt-3 text-sm text-error dark:text-red-300 underline hover:no-underline"
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
          <h2 class="text-xl font-semibold mb-4 text-primary dark:text-blue-400">{projectName}</h2>

          <!-- NSSM Services -->
          {#if project.nssm_services.length > 0}
            <section class="mb-4">
              <h3 class="text-lg font-medium mb-2 text-foreground dark:text-gray-300">Windows 서비스</h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                {#each project.nssm_services as svc}
                  <div class="p-3 rounded border flex justify-between items-center
                    {svc.status === 'Running' ? 'border-green-500 bg-success-light dark:bg-green-900/20' : 'border-red-500 bg-error-light dark:bg-red-900/20'}">
                    <div>
                      <div class="font-medium text-foreground dark:text-white">{svc.name}</div>
                      <div class="text-xs text-muted-foreground dark:text-muted-foreground">{svc.display_name}</div>
                      <span class="px-2 py-0.5 rounded text-xs mt-1 inline-block
                        {svc.status === 'Running' ? 'bg-green-200 dark:bg-green-800 text-success dark:text-green-200' : 'bg-red-200 dark:bg-red-800 text-error dark:text-red-200'}">
                        {svc.status}
                      </span>
                    </div>
                    <div class="flex gap-1">
                      {#if svc.status === 'Running'}
                        <button
                          class="px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                          disabled={selfRestartState !== 'idle' || actionLoading?.startsWith(`nssm-`)}
                          onclick={selfRestartApi}>
                          {selfRestartState !== 'idle' ? 'Graceful...' : 'Graceful 재시작'}
                        </button>
                        <button
                          class="px-2 py-1 text-xs bg-warning text-white rounded hover:bg-warning/90 disabled:opacity-50"
                          disabled={actionLoading?.startsWith(`nssm-`) || selfRestartState !== 'idle'}
                          onclick={() => stopService(svc.name)}>
                          중지
                        </button>
                      {:else}
                        <button
                          class="px-2 py-1 text-xs bg-success text-white rounded hover:bg-success/90 disabled:opacity-50"
                          disabled={actionLoading?.startsWith(`nssm-`)}
                          onclick={() => startService(svc.name)}>
                          시작
                        </button>
                      {/if}
                    </div>
                  </div>
                {/each}
              </div>

              <!-- Self-restart 진행 상태 -->
              {#if selfRestartState !== 'idle'}
                <div class="mt-3 p-3 rounded-lg text-sm flex items-center gap-2
                  {selfRestartState === 'done' ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' :
                   selfRestartState === 'failed' ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300' :
                   'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'}">
                  {#if selfRestartState === 'done'}
                    <span>OK</span>
                  {:else if selfRestartState === 'failed'}
                    <span>!</span>
                    <button
                      class="ml-auto text-xs underline hover:no-underline"
                      onclick={() => { selfRestartState = 'idle'; selfRestartMessage = ''; }}>
                      닫기
                    </button>
                  {:else}
                    <div class="inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-t-transparent"></div>
                  {/if}
                  <span>{selfRestartMessage}</span>
                </div>
              {/if}
            </section>
          {/if}

          <!-- Startup Programs -->
          {#if project.startup_programs.length > 0}
            <section class="mb-4">
              <h3 class="text-lg font-medium mb-2 text-foreground dark:text-gray-300">시작프로그램</h3>
              <table class="w-full text-sm">
                <thead class="bg-muted dark:bg-gray-700">
                  <tr>
                    <th class="text-left p-2 text-foreground dark:text-gray-300">이름</th>
                    <th class="text-left p-2 text-foreground dark:text-gray-300">상태</th>
                    <th class="text-left p-2 text-foreground dark:text-gray-300">액션</th>
                  </tr>
                </thead>
                <tbody>
                  {#each project.startup_programs as prog}
                    <tr class="border-b dark:border-gray-700">
                      <td class="p-2 text-foreground dark:text-white">{prog.name}</td>
                      <td class="p-2">
                        <span class="text-success dark:text-green-400">등록됨</span>
                      </td>
                      <td class="p-2">
                        <button
                          class="px-2 py-1 text-xs bg-error text-white rounded hover:bg-error/90 disabled:opacity-50"
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
              <h3 class="text-lg font-medium mb-2 text-foreground dark:text-gray-300">예약 작업</h3>
              <div class="overflow-x-auto">
                <table class="w-full text-sm">
                  <thead class="bg-muted dark:bg-gray-700">
                    <tr>
                      <th class="text-left p-2 text-foreground dark:text-gray-300">작업명</th>
                      <th class="text-left p-2 text-foreground dark:text-gray-300">상태</th>
                      <th class="text-left p-2 text-foreground dark:text-gray-300">마지막 실행</th>
                      <th class="text-left p-2 text-foreground dark:text-gray-300">다음 실행</th>
                      <th class="text-left p-2 text-foreground dark:text-gray-300">결과</th>
                      <th class="text-left p-2 text-foreground dark:text-gray-300">액션</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each project.scheduled_tasks as task}
                      <tr class="border-b dark:border-gray-700">
                        <td class="p-2 font-medium text-foreground dark:text-white" title={task.Description || ''}>
                          {task.Name}
                        </td>
                        <td class="p-2">
                          <span class="px-2 py-0.5 rounded text-xs
                            {task.State === 'Ready' ? 'bg-green-200 dark:bg-green-800 text-success dark:text-green-200' : 'bg-yellow-200 dark:bg-yellow-800 text-warning-foreground dark:text-yellow-200'}">
                            {task.State}
                          </span>
                        </td>
                        <td class="p-2 text-muted-foreground dark:text-muted-foreground text-xs">{formatDateTime(task.LastRun)}</td>
                        <td class="p-2 text-xs text-foreground dark:text-white">{formatDateTime(task.NextRun)}</td>
                        <td class="p-2 text-xs
                          {task.LastResult === 0 ? 'text-success dark:text-green-400' : task.LastResult !== null ? 'text-error dark:text-red-400' : 'text-muted-foreground'}">
                          {getTaskResultText(task.LastResult)}
                        </td>
                        <td class="p-2 space-x-1">
                          <button
                            class="px-2 py-1 text-xs bg-primary text-white rounded hover:bg-primary-hover disabled:opacity-50"
                            disabled={actionLoading?.startsWith(`run-${task.Folder}`)}
                            onclick={() => runTask(task.Folder, task.Name)}>
                            실행
                          </button>
                          <button
                            class="px-2 py-1 text-xs bg-error text-white rounded hover:bg-error/90 disabled:opacity-50"
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
                <div class="flex items-center gap-3">
                  <h3 class="text-lg font-medium text-foreground dark:text-gray-300">워커 프로세스</h3>
                  <span class="text-xs text-muted-foreground dark:text-gray-500 flex items-center gap-2">
                    <span class="flex items-center gap-0.5"><span class="inline-block w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-600"></span> 왓치독</span>
                    <span class="flex items-center gap-0.5"><span class="inline-block w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-600"></span> 워커</span>
                  </span>
                </div>
                <button
                  class="px-3 py-1 text-xs bg-primary text-white rounded hover:bg-primary-hover disabled:opacity-50"
                  disabled={actionLoading === 'workers'}
                  onclick={restartWorkers}>
                  워커 재시작
                </button>
              </div>
              <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                {#each project.worker_processes as proc}
                  {@const primaryStatus = proc.worker ?? proc.watchdog}
                  {@const isRunning = primaryStatus?.running ?? false}
                  <div class="p-3 rounded border {isRunning ? 'border-green-500 dark:border-green-600' : 'border-border dark:border-gray-600'}">
                    <div class="flex justify-between items-center">
                      <span class="font-medium text-foreground dark:text-white">{proc.label}</span>
                      <span class="flex items-center gap-1">
                        {#if proc.watchdog}
                          <span
                            class="inline-block w-2 h-2 rounded-full {proc.watchdog.running ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'}"
                            title="왓치독: {proc.watchdog.running ? `Running (PID: ${proc.watchdog.pid})` : 'Stopped'}"
                          ></span>
                        {/if}
                        {#if proc.worker}
                          <span
                            class="inline-block w-2 h-2 rounded-full {proc.worker.running ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'}"
                            title="워커: {proc.worker.running ? `Running (PID: ${proc.worker.pid})` : 'Stopped'}"
                          ></span>
                        {/if}
                      </span>
                    </div>
                    <div class="text-sm">
                      {#if isRunning}
                        <span class="text-success dark:text-green-400">Running</span>
                        {#if primaryStatus?.pid}
                          <span class="text-xs text-muted-foreground dark:text-muted-foreground ml-1">(PID: {primaryStatus.pid})</span>
                        {/if}
                      {:else}
                        <span class="text-muted-foreground dark:text-muted-foreground">Stopped</span>
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
