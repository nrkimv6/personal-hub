<script lang="ts">
  import { onMount } from 'svelte';
  import { serviceDashboardApi, systemApi } from '$lib/api';
  import type { ServiceDashboardStatus, RedisStatus, NssmService, WorkerProcess, ScheduledTask, StartupProgram } from '$lib/api';
  import { autoNextRunnerApi } from '$lib/api/auto-next';
  import type { RunStatusResponse } from '$lib/api/auto-next';
  import StatusDot from '$lib/components/ui/StatusDot.svelte';
  import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import SectionSkeleton from '$lib/components/ui/SectionSkeleton.svelte';

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

  // Auto-Next + Redis 상태
  let autoNextStatus = $state<RunStatusResponse | null>(null);
  let redisStatus = $state<RedisStatus | null>(null);

  // ConfirmDialog 상태
  let confirmDialog = $state({ open: false, title: '', description: '', confirmText: '확인', destructive: false, action: () => {} });

  const REFRESH_INTERVAL = 30000;

  // === 데이터 변환 (프로젝트별 → 카테고리별) ===
  let allServices = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap(p => p.nssm_services);
  });

  let allWorkers = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap(p => p.worker_processes);
  });

  let allTasks = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap(p => p.scheduled_tasks);
  });

  let allStartups = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap(p => p.startup_programs);
  });

  // === KPI 계산 ===
  let runningServices = $derived(allServices.filter(s => s.status === 'Running').length);
  let healthyWorkers = $derived(allWorkers.filter(w => {
    const wd = w.watchdog?.running ?? false;
    const wk = w.worker?.running ?? false;
    return wd || wk;
  }).length);
  let taskErrors = $derived(allTasks.filter(t => t.LastResult !== null && t.LastResult !== 0).length);

  // === 그룹핑 ===
  function groupBy<T extends { project: string }>(items: T[]): Record<string, T[]> {
    const groups: Record<string, T[]> = {};
    for (const item of items) {
      (groups[item.project] ??= []).push(item);
    }
    return groups;
  }

  function groupTasksByFolder(tasks: ScheduledTask[]): Record<string, ScheduledTask[]> {
    const groups: Record<string, ScheduledTask[]> = {};
    for (const task of tasks) {
      (groups[task.Folder] ??= []).push(task);
    }
    return groups;
  }

  // === 유틸리티 ===
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
    } catch { return isoString; }
  }

  function formatDateTime(isoString: string | null): string {
    if (!isoString) return '-';
    try {
      const date = new Date(isoString);
      const now = new Date();
      const isToday = date.toDateString() === now.toDateString();
      if (isToday) return `오늘 ${date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`;
      return `${date.getMonth() + 1}월 ${date.getDate()}일 ${date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`;
    } catch { return isoString; }
  }

  function formatUptime(seconds: number | null): string {
    if (seconds === null) return '-';
    if (seconds < 60) return `${seconds}초`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}분`;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${h}시간 ${m}분`;
  }

  function serviceVariant(svc: NssmService): 'success' | 'warning' | 'error' | 'gray' {
    if (svc.status === 'Running') return 'success';
    if (svc.status === 'StartPending' || svc.status === 'StopPending') return 'warning';
    return 'error';
  }

  function workerVariant(w: WorkerProcess): 'success' | 'warning' | 'error' | 'gray' {
    const wd = w.watchdog?.running ?? false;
    const wk = w.worker?.running ?? false;
    if (wd && wk) return 'success';
    if (wd && !wk) return 'warning';
    return 'error';
  }

  function workerStatusText(w: WorkerProcess): { text: string; variant: 'success' | 'warning' | 'error' } {
    const wd = w.watchdog?.running ?? false;
    const wk = w.worker?.running ?? false;
    if (wd && wk) return { text: '정상', variant: 'success' };
    if (wd && !wk) return { text: '워커 중지', variant: 'warning' };
    if (!wd && wk) return { text: 'WD 없음', variant: 'warning' };
    return { text: '중지됨', variant: 'error' };
  }

  function taskVariant(state: string): 'success' | 'warning' | 'gray' {
    if (state === 'Ready') return 'success';
    if (state === 'Running') return 'warning';
    return 'gray';
  }

  // Graceful restart 단계
  const restartSteps = [
    { key: 'requested', label: '요청' },
    { key: 'waiting', label: '대기' },
    { key: 'checking', label: '확인' },
    { key: 'done', label: '완료' },
  ] as const;

  function stepStatus(stepKey: string): 'active' | 'done' | 'pending' | 'failed' {
    const order = ['requested', 'waiting', 'checking', 'done'];
    const currentIdx = order.indexOf(selfRestartState);
    const stepIdx = order.indexOf(stepKey);
    if (selfRestartState === 'failed') {
      return stepIdx <= currentIdx ? 'failed' : 'pending';
    }
    if (stepIdx < currentIdx) return 'done';
    if (stepIdx === currentIdx) return 'active';
    return 'pending';
  }

  // === 확인 다이얼로그 헬퍼 ===
  function showConfirm(title: string, description: string, action: () => void, destructive = false, confirmText = '확인') {
    confirmDialog = { open: true, title, description, confirmText, destructive, action };
  }

  // === API 호출 ===
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

  function updateServiceCounts() {
    if (status && onStatusChange) {
      let running = 0, total = 0;
      for (const project of Object.values(status.projects)) {
        for (const svc of project.nssm_services) {
          total++;
          if (svc.status === 'Running') running++;
        }
      }
      onStatusChange(running, total);
    }
  }

  async function fetchExtraStatus() {
    try {
      const [anStatus, rStatus] = await Promise.all([
        autoNextRunnerApi.status().catch(() => null),
        serviceDashboardApi.redisStatus().catch(() => null),
      ]);
      autoNextStatus = anStatus;
      redisStatus = rStatus;
    } catch { /* graceful */ }
  }

  onMount(() => {
    fetchStatus();
    fetchExtraStatus();
    const interval = setInterval(() => { fetchStatus(); fetchExtraStatus(); }, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  });

  // === 관리 기능 ===
  async function stopService(name: string) {
    actionLoading = `nssm-stop-${name}`;
    try {
      await serviceDashboardApi.stopNssm(name);
      await fetchStatus();
    } catch (e) {
      alert(`중지 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function startService(name: string) {
    actionLoading = `nssm-start-${name}`;
    try {
      await serviceDashboardApi.startNssm(name);
      await fetchStatus();
    } catch (e) {
      alert(`시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function removeStartup(name: string) {
    actionLoading = `startup-${name}`;
    try {
      await serviceDashboardApi.removeStartup(name);
      await fetchStatus();
    } catch (e) {
      alert(`제거 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function runTask(folder: string, name: string) {
    actionLoading = `run-${folder}-${name}`;
    try {
      await serviceDashboardApi.runTask(folder, name);
      await fetchStatus();
    } catch (e) {
      alert(`실행 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function removeTask(folder: string, name: string) {
    actionLoading = `task-${folder}-${name}`;
    try {
      await serviceDashboardApi.removeTask(folder, name);
      await fetchStatus();
    } catch (e) {
      alert(`제거 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function restartWorkers() {
    actionLoading = 'workers';
    try {
      await serviceDashboardApi.restartWorkers();
      await fetchStatus();
    } catch (e) {
      alert(`재시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function restartSingleWorker(name: string, label: string) {
    actionLoading = `worker-${name}`;
    try {
      await serviceDashboardApi.restartWorker(name);
      await fetchStatus();
    } catch (e) {
      alert(`재시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function stopWatchdogs() {
    actionLoading = 'watchdogs-stop';
    try {
      await serviceDashboardApi.stopWatchdogs();
      await fetchStatus();
    } catch (e) {
      alert(`중지 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function startWatchdogs() {
    if (redisStatus && !redisStatus.connected) {
      alert('Redis가 연결되지 않았습니다.\nwatchdog 시작은 Redis Command Listener를 경유합니다.\n\nCLI에서 실행: python scripts/browser_workers.py start');
      return;
    }
    actionLoading = 'watchdogs-start';
    try {
      await serviceDashboardApi.startWatchdogs();
      await fetchStatus();
    } catch (e) {
      alert(`시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}\n\nCLI에서 실행: python scripts/browser_workers.py start`);
    } finally { actionLoading = null; }
  }

  async function selfRestartApi() {
    selfRestartState = 'requested';
    selfRestartMessage = 'Self-restart 요청 중...';
    try {
      const response = await systemApi.selfRestart(2.0);
      selfRestartState = 'waiting';
      selfRestartMessage = `PID ${response.pid} 종료 대기 중...`;
      await new Promise(r => setTimeout(r, 15000));
      selfRestartState = 'checking';
      selfRestartMessage = 'API 재시작 확인 중...';
      let success = false;
      for (let i = 1; i <= 6; i++) {
        try {
          await systemApi.status();
          success = true;
          break;
        } catch {
          selfRestartMessage = `API 응답 대기 중... (${i}/6)`;
          if (i < 6) await new Promise(r => setTimeout(r, 5000));
        }
      }
      if (success) {
        selfRestartState = 'done';
        selfRestartMessage = 'API 재시작 완료';
        await fetchStatus();
        setTimeout(() => { selfRestartState = 'idle'; selfRestartMessage = ''; }, 3000);
      } else {
        selfRestartState = 'failed';
        selfRestartMessage = 'API 재시작 확인 실패. 수동 확인 필요.';
      }
    } catch (e) {
      selfRestartState = 'failed';
      selfRestartMessage = `요청 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`;
    }
  }

  async function stopAutoNext() {
    actionLoading = 'auto-next-stop';
    try {
      await autoNextRunnerApi.stop();
      await fetchExtraStatus();
    } catch (e) {
      alert(`중지 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function resetAutoNext() {
    actionLoading = 'auto-next-reset';
    try {
      await autoNextRunnerApi.resetState();
      await fetchExtraStatus();
    } catch (e) {
      alert(`리셋 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally { actionLoading = null; }
  }

  async function restartRedis() {
    actionLoading = 'redis-restart';
    try {
      const result = await serviceDashboardApi.restartRedis();
      alert(result.message);
      await fetchExtraStatus();
    } catch (e) {
      alert(`재시작 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}\n\nCLI: browser_workers.py redis-restart`);
    } finally { actionLoading = null; }
  }
</script>

<!-- ConfirmDialog (전역 1개) -->
<ConfirmDialog
  bind:open={confirmDialog.open}
  title={confirmDialog.title}
  description={confirmDialog.description}
  confirmText={confirmDialog.confirmText}
  destructive={confirmDialog.destructive}
  onConfirm={confirmDialog.action}
  onCancel={() => {}}
/>

<div class="space-y-4 max-w-6xl mx-auto">

  <!-- ============================================================ -->
  <!-- Status Overview -->
  <!-- ============================================================ -->
  {#if loading}
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {#each Array(4) as _}
        <div class="bg-card rounded-lg border border-border shadow-card p-4">
          <div class="h-4 w-20 rounded animate-skeleton-shimmer mb-2"></div>
          <div class="h-7 w-12 rounded animate-skeleton-shimmer"></div>
        </div>
      {/each}
    </div>
  {:else if error}
    <div class="bg-error-light border border-error/20 rounded-lg p-4">
      <p class="text-error font-medium">{error}</p>
      <button onclick={fetchStatus} class="mt-2 text-sm text-error underline hover:no-underline">다시 시도</button>
    </div>
  {:else if status}
    <!-- Overview 카드 + 액션 바 -->
    <div class="bg-card rounded-lg border border-border shadow-card p-4">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <h2 class="text-base font-semibold text-foreground">Status Overview</h2>
        <div class="flex items-center gap-2">
          <button
            onclick={fetchStatus}
            class="h-8 px-3 text-xs rounded-md font-medium border border-input bg-background hover:bg-accent transition-colors"
          >
            새로고침
          </button>
          <button
            onclick={refreshStatus}
            disabled={refreshing}
            class="h-8 px-3 text-xs rounded-md font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50 transition-colors"
          >
            {refreshing ? '수집 중...' : '즉시 수집'}
          </button>
        </div>
      </div>

      <!-- 4 KPI -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
        <!-- NSSM Services -->
        <div class="flex items-center gap-3 p-3 rounded-lg bg-muted/40">
          <div class="flex items-center justify-center h-9 w-9 rounded-md {runningServices === allServices.length ? 'bg-success-light' : 'bg-warning-light'}">
            <StatusDot variant={runningServices === allServices.length ? 'success' : 'warning'} size="md" pulse={runningServices === allServices.length} />
          </div>
          <div>
            <div class="text-xs text-muted-foreground">NSSM 서비스</div>
            <div class="text-lg font-semibold font-mono">{runningServices}<span class="text-sm text-muted-foreground font-normal">/{allServices.length}</span></div>
          </div>
        </div>

        <!-- Workers -->
        <div class="flex items-center gap-3 p-3 rounded-lg bg-muted/40">
          <div class="flex items-center justify-center h-9 w-9 rounded-md {healthyWorkers === allWorkers.length ? 'bg-success-light' : 'bg-warning-light'}">
            <StatusDot variant={healthyWorkers === allWorkers.length ? 'success' : 'warning'} size="md" pulse={healthyWorkers === allWorkers.length} />
          </div>
          <div>
            <div class="text-xs text-muted-foreground">워커 프로세스</div>
            <div class="text-lg font-semibold font-mono">{healthyWorkers}<span class="text-sm text-muted-foreground font-normal">/{allWorkers.length}</span></div>
          </div>
        </div>

        <!-- Tasks -->
        <div class="flex items-center gap-3 p-3 rounded-lg bg-muted/40">
          <div class="flex items-center justify-center h-9 w-9 rounded-md {taskErrors > 0 ? 'bg-error-light' : 'bg-muted'}">
            <StatusDot variant={taskErrors > 0 ? 'error' : 'gray'} size="md" />
          </div>
          <div>
            <div class="text-xs text-muted-foreground">예약 작업</div>
            <div class="text-lg font-semibold font-mono">{allTasks.length}
              {#if taskErrors > 0}<span class="text-xs text-error font-normal ml-1">({taskErrors} 에러)</span>{/if}
            </div>
          </div>
        </div>

        <!-- Startups -->
        <div class="flex items-center gap-3 p-3 rounded-lg bg-muted/40">
          <div class="flex items-center justify-center h-9 w-9 rounded-md bg-muted">
            <StatusDot variant="gray" size="md" />
          </div>
          <div>
            <div class="text-xs text-muted-foreground">시작프로그램</div>
            <div class="text-lg font-semibold font-mono">{allStartups.length}</div>
          </div>
        </div>
      </div>

      <!-- 수집 시각 + 자동 갱신 -->
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <StatusDot variant="success" size="sm" pulse />
        <span>자동 갱신 30초</span>
        <span class="mx-1">·</span>
        <span>마지막 수집: {formatCollectedAt(status.collected_at)}</span>
      </div>
    </div>

    <!-- ============================================================ -->
    <!-- Services + Workers (2-col) -->
    <!-- ============================================================ -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">

      <!-- Windows Services -->
      <div class="bg-card rounded-lg border border-border shadow-card p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <h3 class="text-sm font-semibold text-foreground">Windows 서비스</h3>
            <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">{allServices.length}</span>
          </div>
          <button
            onclick={() => showConfirm('Graceful 재시작', 'API 서버를 재시작합니다. 약 15초간 서비스가 중단됩니다.', selfRestartApi, true, '재시작')}
            disabled={selfRestartState !== 'idle'}
            class="h-7 px-2 text-[11px] rounded-md font-medium border border-input bg-background hover:bg-accent transition-colors disabled:opacity-50"
          >
            Graceful 재시작
          </button>
        </div>

        <!-- Graceful Restart 진행바 -->
        {#if selfRestartState !== 'idle'}
          <div class="mb-3 p-3 rounded-lg bg-muted/50">
            <div class="flex items-center gap-1 mb-2">
              {#each restartSteps as step, i}
                {@const s = stepStatus(step.key)}
                {#if i > 0}
                  <div class="h-px w-4 {s === 'done' || s === 'active' ? 'bg-primary' : s === 'failed' ? 'bg-error' : 'bg-border'}"></div>
                {/if}
                <div class="flex items-center gap-1">
                  <div class="h-2 w-2 rounded-full {s === 'done' ? 'bg-success' : s === 'active' ? 'bg-primary animate-pulse-soft' : s === 'failed' ? 'bg-error' : 'bg-muted-foreground/30'}"></div>
                  <span class="text-[10px] {s === 'active' ? 'text-primary font-medium' : s === 'failed' ? 'text-error' : 'text-muted-foreground'}">{step.label}</span>
                </div>
              {/each}
            </div>
            <div class="flex items-center gap-2 text-xs">
              {#if selfRestartState !== 'done' && selfRestartState !== 'failed'}
                <div class="inline-block animate-spin rounded-full h-3 w-3 border-2 border-primary border-t-transparent"></div>
              {/if}
              <span class="text-muted-foreground">{selfRestartMessage}</span>
              {#if selfRestartState === 'failed'}
                <button onclick={() => { selfRestartState = 'idle'; selfRestartMessage = ''; }} class="text-xs text-error underline ml-auto">닫기</button>
              {/if}
            </div>
          </div>
        {/if}

        <!-- 프로젝트별 서비스 -->
        {#each Object.entries(groupBy(allServices)) as [project, services]}
          <div class="mb-2 last:mb-0">
            <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-3 py-1">{project}</div>
            {#each services as svc}
              <div class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 rounded transition-colors">
                <StatusDot variant={serviceVariant(svc)} size="sm" pulse={svc.status === 'Running'} />
                <span class="font-medium text-sm text-foreground truncate">{svc.display_name}</span>
                <span class="font-mono text-[11px] text-muted-foreground truncate hidden sm:inline">{svc.name}</span>
                <div class="ml-auto flex items-center gap-2 shrink-0">
                  <StatusBadge variant={serviceVariant(svc)} size="sm">{svc.status}</StatusBadge>
                  <span class="text-[10px] text-muted-foreground">{svc.start_type}</span>
                  {#if svc.status === 'Running'}
                    <button
                      onclick={() => showConfirm('서비스 중지', `"${svc.display_name}" 서비스를 중지합니다.`, () => stopService(svc.name), true, '중지')}
                      disabled={actionLoading?.startsWith('nssm-')}
                      class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-error hover:bg-error-light transition-colors disabled:opacity-50"
                      title="중지"
                    >
                      <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" rx="1"/></svg>
                    </button>
                  {:else}
                    <button
                      onclick={() => startService(svc.name)}
                      disabled={actionLoading?.startsWith('nssm-')}
                      class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-success hover:bg-success-light transition-colors disabled:opacity-50"
                      title="시작"
                    >
                      <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 16 16"><path d="M4 2l10 6-10 6V2z"/></svg>
                    </button>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/each}

        {#if allServices.length === 0}
          <p class="text-sm text-muted-foreground py-4 text-center">서비스 정보가 없습니다.</p>
        {/if}
      </div>

      <!-- Worker Processes -->
      <div class="bg-card rounded-lg border border-border shadow-card p-4">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <h3 class="text-sm font-semibold text-foreground">워커 프로세스</h3>
            <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">{allWorkers.length}</span>
            <span class="text-[10px] text-muted-foreground flex items-center gap-2 ml-1">
              <span class="flex items-center gap-0.5"><span class="inline-block w-1.5 h-1.5 rounded-full bg-muted-foreground/40"></span>WD</span>
              <span class="flex items-center gap-0.5"><span class="inline-block w-1.5 h-1.5 rounded-full bg-muted-foreground/40"></span>WK</span>
            </span>
          </div>
          <div class="flex items-center gap-1">
            <button
              onclick={() => showConfirm('전체 재시작', '모든 워커를 재시작합니다. watchdog가 자동으로 재시작합니다.', restartWorkers)}
              disabled={actionLoading === 'workers'}
              class="h-7 px-2 text-[11px] rounded-md font-medium border border-input bg-background hover:bg-accent transition-colors disabled:opacity-50"
            >
              전체 재시작
            </button>
            <button
              onclick={() => showConfirm('Watchdog 중지', '모든 watchdog를 중지합니다. 워커가 죽어도 자동 재시작되지 않습니다.', stopWatchdogs, true, '중지')}
              disabled={actionLoading === 'watchdogs-stop'}
              class="h-7 px-2 text-[11px] rounded-md font-medium text-warning border border-warning/30 bg-warning-light hover:bg-warning/10 transition-colors disabled:opacity-50"
            >
              WD 중지
            </button>
            <button
              onclick={() => startWatchdogs()}
              disabled={actionLoading === 'watchdogs-start'}
              class="h-7 px-2 text-[11px] rounded-md font-medium text-success border border-success/30 bg-success-light hover:bg-success/10 transition-colors disabled:opacity-50"
              title={redisStatus && !redisStatus.connected ? 'Redis 연결 필요' : ''}
            >
              WD 시작
            </button>
          </div>
        </div>

        {#each allWorkers as proc}
          {@const ws = workerStatusText(proc)}
          <div class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 rounded transition-colors">
            <StatusDot variant={workerVariant(proc)} size="sm" pulse={workerVariant(proc) === 'success'} />
            <span class="font-medium text-sm text-foreground">{proc.label}</span>
            <span class="font-mono text-[11px] text-muted-foreground hidden sm:inline">{proc.name}</span>

            <!-- WD/WK dots -->
            <div class="ml-auto flex items-center gap-3 shrink-0">
              <span class="flex items-center gap-1">
                {#if proc.watchdog}
                  <span
                    class="inline-block w-1.5 h-1.5 rounded-full {proc.watchdog.running ? 'bg-success' : 'bg-muted-foreground/30'}"
                    title="Watchdog: {proc.watchdog.running ? `Running (PID: ${proc.watchdog.pid})` : 'Stopped'}"
                  ></span>
                {/if}
                {#if proc.worker}
                  <span
                    class="inline-block w-1.5 h-1.5 rounded-full {proc.worker.running ? 'bg-success' : 'bg-muted-foreground/30'}"
                    title="Worker: {proc.worker.running ? `Running (PID: ${proc.worker.pid})` : 'Stopped'}"
                  ></span>
                {/if}
              </span>

              <span class="text-[11px] font-medium text-{ws.variant}">{ws.text}</span>

              {#if proc.worker && proc.name !== 'api_watchdog'}
                <button
                  onclick={() => showConfirm('워커 재시작', `"${proc.label}" 워커를 재시작합니다.`, () => restartSingleWorker(proc.name, proc.label))}
                  disabled={actionLoading === `worker-${proc.name}`}
                  class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
                >
                  재시작
                </button>
              {/if}
            </div>
          </div>
        {/each}

        {#if allWorkers.length === 0}
          <p class="text-sm text-muted-foreground py-4 text-center">워커 정보가 없습니다.</p>
        {/if}
      </div>
    </div>

    <!-- ============================================================ -->
    <!-- Tasks + Infrastructure (3-col) -->
    <!-- ============================================================ -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">

      <!-- Scheduled Tasks -->
      <div class="lg:col-span-2 bg-card rounded-lg border border-border shadow-card p-4">
        <div class="flex items-center gap-2 mb-3">
          <h3 class="text-sm font-semibold text-foreground">예약 작업</h3>
          <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">{allTasks.length}</span>
        </div>

        {#each Object.entries(groupTasksByFolder(allTasks)) as [folder, tasks]}
          <div class="mb-2 last:mb-0">
            <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-3 py-1">{folder}</div>
            {#each tasks as task}
              <div class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 rounded transition-colors text-sm">
                <span class="font-medium text-foreground truncate" title={task.Description || ''}>{task.Name}</span>

                {#if task.LastResult !== null && task.LastResult !== 0}
                  <span class="text-error shrink-0" title="Error: 0x{task.LastResult.toString(16).toUpperCase()}">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/><line x1="12" y1="8" x2="12" y2="12" stroke-width="2"/><line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2"/></svg>
                  </span>
                {/if}

                <div class="ml-auto flex items-center gap-2 shrink-0">
                  <span class="text-[10px] text-muted-foreground hidden md:inline" title="마지막 실행">{formatDateTime(task.LastRun)}</span>
                  <span class="text-[10px] text-foreground hidden lg:inline" title="다음 실행">{formatDateTime(task.NextRun)}</span>
                  <StatusBadge variant={taskVariant(task.State)} size="sm">{task.State}</StatusBadge>

                  <button
                    onclick={() => runTask(task.Folder, task.Name)}
                    disabled={actionLoading?.startsWith(`run-${task.Folder}`)}
                    class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-primary hover:bg-primary-light transition-colors disabled:opacity-50"
                    title="실행"
                  >
                    <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 16 16"><path d="M4 2l10 6-10 6V2z"/></svg>
                  </button>
                  <button
                    onclick={() => showConfirm('작업 제거', `예약 작업 "${folder}/${task.Name}"을 제거합니다. (관리자 권한 필요)`, () => removeTask(task.Folder, task.Name), true, '제거')}
                    disabled={actionLoading?.startsWith(`task-${task.Folder}`)}
                    class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-error hover:bg-error-light transition-colors disabled:opacity-50"
                    title="제거"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14"/></svg>
                  </button>
                </div>
              </div>
            {/each}
          </div>
        {/each}

        {#if allTasks.length === 0}
          <p class="text-sm text-muted-foreground py-4 text-center">예약 작업이 없습니다.</p>
        {/if}
      </div>

      <!-- Infrastructure -->
      <div class="bg-card rounded-lg border border-border shadow-card p-4">
        <h3 class="text-sm font-semibold text-foreground mb-3">인프라</h3>

        <!-- Redis -->
        {#if redisStatus}
          <div class="mb-3 pb-3 border-b border-border">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <StatusDot variant={redisStatus.connected ? 'success' : 'error'} size="md" pulse={redisStatus.connected} />
                <span class="font-medium text-sm">Redis</span>
                <StatusBadge variant={redisStatus.connected ? 'success' : 'error'} size="sm">
                  {redisStatus.connected ? 'Connected' : 'Disconnected'}
                </StatusBadge>
              </div>
              <button
                onclick={() => showConfirm('Redis 재시작', 'Redis를 재시작합니다. Session 0에서는 실패할 수 있습니다.', restartRedis, true, '재시작')}
                disabled={actionLoading === 'redis-restart'}
                class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
              >
                재시작
              </button>
            </div>
            {#if redisStatus.container_running !== null}
              <div class="text-[10px] text-muted-foreground mb-1 px-1">
                Container: {redisStatus.container_running ? 'Running' : 'Stopped'}
              </div>
            {/if}
            {#if redisStatus.connected}
              <div class="flex gap-3 text-[10px] text-muted-foreground px-1">
                <span>Uptime: {formatUptime(redisStatus.uptime_seconds)}</span>
                <span>Mem: {redisStatus.used_memory_mb ?? '-'}MB</span>
                <span>Clients: {redisStatus.connected_clients ?? '-'}</span>
              </div>
            {/if}
          </div>
        {/if}

        <!-- Auto-Next -->
        {#if autoNextStatus}
          <div class="mb-3 pb-3 border-b border-border">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <StatusDot
                  variant={autoNextStatus.running ? 'success' : autoNextStatus.crashed ? 'error' : 'gray'}
                  size="md"
                  pulse={autoNextStatus.running}
                />
                <span class="font-medium text-sm">Auto-Next</span>
                <StatusBadge
                  variant={autoNextStatus.running ? 'success' : autoNextStatus.crashed ? 'error' : 'gray'}
                  size="sm"
                >
                  {autoNextStatus.running ? 'Running' : autoNextStatus.crashed ? 'Crashed' : 'Stopped'}
                </StatusBadge>
              </div>
              <div class="flex gap-1">
                {#if autoNextStatus.running}
                  <button
                    onclick={() => showConfirm('Auto-Next 중지', 'Auto-Next를 중지합니다.', stopAutoNext, true, '중지')}
                    disabled={actionLoading === 'auto-next-stop'}
                    class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    중지
                  </button>
                {:else if autoNextStatus.crashed}
                  <button
                    onclick={() => showConfirm('Auto-Next 리셋', 'RUNNING → PENDING 상태로 리셋합니다.', resetAutoNext)}
                    disabled={actionLoading === 'auto-next-reset'}
                    class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
                  >
                    리셋
                  </button>
                {/if}
              </div>
            </div>
            {#if autoNextStatus.pid}
              <div class="text-[10px] text-muted-foreground px-1">PID: {autoNextStatus.pid}</div>
            {/if}
            {#if autoNextStatus.plan_file}
              <div class="text-[10px] text-muted-foreground px-1 truncate" title={autoNextStatus.plan_file}>
                {autoNextStatus.plan_file}
              </div>
            {/if}
            {#if autoNextStatus.running && autoNextStatus.start_time}
              <div class="text-[10px] text-muted-foreground px-1">시작: {formatCollectedAt(autoNextStatus.start_time)}</div>
            {/if}
            <!-- 경고 -->
            {#if !autoNextStatus.running && !autoNextStatus.redis_connected}
              <div class="mt-1 text-[10px] text-error px-1 flex items-center gap-1">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/><line x1="12" y1="8" x2="12" y2="12" stroke-width="2"/><line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2"/></svg>
                Redis 미연결
              </div>
            {:else if !autoNextStatus.running && !autoNextStatus.listener_alive && autoNextStatus.redis_connected}
              <div class="mt-1 text-[10px] text-warning px-1 flex items-center gap-1">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/><line x1="12" y1="8" x2="12" y2="12" stroke-width="2"/><line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2"/></svg>
                Command Listener 미실행
              </div>
            {/if}
          </div>
        {/if}

        <!-- Startup Programs -->
        <div>
          <div class="flex items-center gap-2 mb-2">
            <span class="text-xs font-medium text-muted-foreground">시작프로그램</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">{allStartups.length}</span>
          </div>
          {#each allStartups as prog}
            <div class="flex items-center gap-2 px-1 py-1.5 text-sm">
              <span class="font-medium text-foreground text-xs">{prog.name}</span>
              <span class="text-[10px] text-muted-foreground truncate" title={prog.path}>{prog.project}</span>
              <button
                onclick={() => showConfirm('시작프로그램 제거', `"${prog.name}" 시작프로그램을 제거합니다.`, () => removeStartup(prog.name), true, '제거')}
                disabled={actionLoading === `startup-${prog.name}`}
                class="ml-auto h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-error hover:bg-error-light transition-colors disabled:opacity-50 shrink-0"
                title="제거"
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14"/></svg>
              </button>
            </div>
          {/each}
          {#if allStartups.length === 0}
            <p class="text-[11px] text-muted-foreground py-2 text-center">시작프로그램이 없습니다.</p>
          {/if}
        </div>
      </div>
    </div>

  {:else}
    <!-- Empty -->
    <div class="bg-card rounded-lg border border-border shadow-card p-8 text-center">
      <p class="text-muted-foreground mb-3">서비스 정보가 없습니다.</p>
      <button
        onclick={refreshStatus}
        disabled={refreshing}
        class="h-9 px-4 text-sm rounded-md font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50 transition-colors"
      >
        즉시 수집
      </button>
    </div>
  {/if}

  <!-- Loading skeleton (전체) -->
  {#if loading}
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <SectionSkeleton rows={4} />
      <SectionSkeleton rows={4} />
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="lg:col-span-2"><SectionSkeleton rows={5} /></div>
      <SectionSkeleton rows={3} />
    </div>
  {/if}
</div>
