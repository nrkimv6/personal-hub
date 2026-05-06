<script lang="ts">
  import { onMount } from 'svelte';
  import { serviceDashboardApi, systemApi, processWatchApi } from '$lib/api';
  import { apiGate } from '$lib/stores/apiGate.svelte';
  import { toast } from '$lib/stores/toast';
  import type {
    ServiceDashboardStatus,
    RedisStatus,
    ProcessWatchItem,
    ProcessWatchLatestResponse,
    NightlyCleanupStats
  } from '$lib/api';
  import { devRunnerRunnerApi } from '$lib/api/dev-runner';
  import type { RunStatusResponse } from '$lib/api/dev-runner';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import SectionSkeleton from '$lib/components/ui/SectionSkeleton.svelte';
  import ServiceDashboardSection from './service-status/ServiceDashboardSection.svelte';
  import ProcessWatchSection from './service-status/ProcessWatchSection.svelte';
  import ProcessKillReasonDialog from './service-status/ProcessKillReasonDialog.svelte';
  import CleanupStatsSection from './service-status/CleanupStatsSection.svelte';
  import { createServiceStatusActions } from './service-status/actions';
  import {
    groupBy,
    groupTasksByFolder,
    formatCollectedAt,
    formatDateTime,
    formatUptime,
    serviceVariant,
    workerVariant,
    workerStatusText,
    workerStatusTextClass,
    taskVariant,
    processWatchKey,
    formatProcessDelta
  } from './service-status/utils';
  import type { ConfirmAction, DbCircuitStatus, RestartStep, RestartStepKey } from './service-status/types';

  interface Props {
    onStatusChange?: (runningCount: number, totalCount: number) => void;
  }
  let { onStatusChange }: Props = $props();

  let status = $state<ServiceDashboardStatus | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let actionLoading = $state<string | null>(null);
  let refreshing = $state(false);

  let selfRestartState = $state<'idle' | 'requested' | 'waiting' | 'checking' | 'done' | 'failed'>('idle');
  let selfRestartMessage = $state('');

  let devRunnerStatus = $state<RunStatusResponse | null>(null);
  let dbStatus = $state<DbCircuitStatus | null>(null);
  let redisStatus = $state<RedisStatus | null>({
    connected: false,
    container_running: null,
    uptime_seconds: null,
    used_memory_mb: null,
    connected_clients: null
  });

  let confirmDialog = $state<{
    open: boolean;
    title: string;
    description: string;
    confirmText: string;
    destructive: boolean;
    action: ConfirmAction;
  }>({
    open: false,
    title: '',
    description: '',
    confirmText: '확인',
    destructive: false,
    action: () => {}
  });

  let cleanupStats = $state<NightlyCleanupStats | null>(null);
  let cleanupStatsLoading = $state(false);

  let processWatchLatest = $state<ProcessWatchLatestResponse | null>(null);
  let processWatchRows = $state<ProcessWatchItem[]>([]);
  let processWatchHistoryRows = $state<ProcessWatchItem[]>([]);
  let processWatchError = $state<string | null>(null);
  let processLoading = $state(false);
  let processWatchInFlight = $state(false);
  let processPollingEnabled = $state(false);
  let processPollingInterval: ReturnType<typeof setInterval> | null = null;
  let processMemBaseline = $state<Record<string, { memoryMb: number; capturedAtMs: number }>>({});
  let processMemDeltaRate = $state<Record<string, number | null>>({});
  let killDialogOpen = $state(false);
  let killDialogItem = $state<ProcessWatchItem | null>(null);
  let killReasonDefault = $state('');

  const PROCESS_REFRESH_INTERVAL = 5000;
  const REFRESH_INTERVAL = 30000;
  const SELF_RESTART_MAX_POLL = 36;
  const SELF_RESTART_POLL_INTERVAL = 5000;
  const SELF_RESTART_INITIAL_WAIT_SELF = 20000;
  const SELF_RESTART_INITIAL_WAIT_REMOTE = 10000;

  const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

  let allServices = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap((project) => project.nssm_services);
  });

  let allWorkers = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap((project) => project.worker_processes);
  });

  let workerTierProcs = $derived(allWorkers.filter((worker) => worker.tier !== 'infra'));
  let infraTierProcs = $derived(allWorkers.filter((worker) => worker.tier === 'infra'));

  let allTasks = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap((project) => project.scheduled_tasks);
  });

  let allStartups = $derived.by(() => {
    if (!status) return [];
    return Object.values(status.projects).flatMap((project) => project.startup_programs);
  });

  let servicesByProject = $derived.by(() => groupBy(allServices));
  let tasksByFolder = $derived.by(() => groupTasksByFolder(allTasks));

  let runningServices = $derived(allServices.filter((service) => service.status === 'Running').length);
  let healthyWorkers = $derived(allWorkers.filter((worker) => {
    const watchdogRunning = worker.watchdog?.running ?? false;
    const workerRunning = worker.worker?.running ?? false;
    return watchdogRunning || workerRunning;
  }).length);
  let taskErrors = $derived(allTasks.filter((task) => task.LastResult !== null && task.LastResult !== 0).length);

  function formatProcessUptime(proc: ProcessWatchItem): string {
    if (proc.uptime_human) return proc.uptime_human;
    if (proc.uptime_seconds !== undefined && proc.uptime_seconds !== null) {
      return formatUptime(proc.uptime_seconds);
    }
    return '-';
  }

  function formatProcessStart(proc: ProcessWatchItem): string {
    if (proc.start_time) return formatDateTime(proc.start_time);
    if (proc.create_time !== undefined && proc.create_time !== null) {
      try {
        return formatDateTime(new Date(proc.create_time * 1000).toISOString());
      } catch {
        return '-';
      }
    }
    return '-';
  }

  function formatAncestorChain(proc: ProcessWatchItem): string {
    const chain = proc.ancestor_chain ?? [];
    if (!chain.length) {
      return proc.parent_name
        ? `${proc.pid}:${proc.name} <- ${proc.ppid ?? '-'}:${proc.parent_name}`
        : `${proc.pid}:${proc.name}`;
    }
    return chain
      .map((node) => `${node.pid}:${node.name || 'unknown'}${node.alive ? '' : ' (dead)'}`)
      .join(' <- ');
  }

  function updateProcessDeltaRates(items: ProcessWatchItem[]) {
    const nextBaseline: Record<string, { memoryMb: number; capturedAtMs: number }> = {};
    const nextRate: Record<string, number | null> = {};

    for (const item of items) {
      const key = processWatchKey(item);
      const capturedAtMs = item.captured_at ? new Date(item.captured_at).getTime() : Date.now();
      const currentMem = Number(item.memory_mb ?? 0);
      const prev = processMemBaseline[key];
      let rate: number | null = null;

      if (prev && capturedAtMs > (prev.capturedAtMs + 500)) {
        const dtSec = (capturedAtMs - prev.capturedAtMs) / 1000;
        const raw = (currentMem - prev.memoryMb) / dtSec;
        rate = Number.isFinite(raw) ? raw : null;
      }

      nextBaseline[key] = { memoryMb: currentMem, capturedAtMs };
      nextRate[key] = rate;
    }

    processMemBaseline = nextBaseline;
    processMemDeltaRate = nextRate;
  }

  function getProcessDeltaRate(proc: ProcessWatchItem): number | null {
    return processMemDeltaRate[processWatchKey(proc)] ?? null;
  }

  function processDeltaTextClass(rate: number | null): string {
    if (rate === null) return 'text-muted-foreground';
    if (rate >= 256) return 'text-error font-semibold';
    if (rate >= 128) return 'text-warning font-semibold';
    if (rate <= -128) return 'text-success font-semibold';
    return 'text-foreground';
  }

  const restartSteps: readonly RestartStep[] = [
    { key: 'requested', label: '요청' },
    { key: 'waiting', label: '대기' },
    { key: 'checking', label: '확인' },
    { key: 'done', label: '완료' }
  ];

  function stepStatus(stepKey: RestartStepKey): 'active' | 'done' | 'pending' | 'failed' {
    const order: RestartStepKey[] = ['requested', 'waiting', 'checking', 'done'];
    if (selfRestartState === 'failed') {
      return stepKey === 'done' ? 'pending' : 'failed';
    }
    if (selfRestartState === 'idle') return 'pending';

    const currentIndex = order.indexOf(selfRestartState as RestartStepKey);
    const stepIndex = order.indexOf(stepKey);
    if (stepIndex < currentIndex) return 'done';
    if (stepIndex === currentIndex) return 'active';
    return 'pending';
  }

  function showConfirm(
    title: string,
    description: string,
    action: ConfirmAction,
    destructive = false,
    confirmText = '확인'
  ) {
    confirmDialog = { open: true, title, description, confirmText, destructive, action };
  }

  const actions = createServiceStatusActions({
    serviceDashboardApi,
    devRunnerRunnerApi,
    fetchStatus,
    fetchExtraStatus,
    getRedisStatus: () => redisStatus,
    getDevRunnerRunnerId: () => devRunnerStatus?.runner_id,
    setActionLoading: (actionKey) => {
      actionLoading = actionKey;
    },
    toast
  });

  async function fetchStatus() {
    try {
      status = await serviceDashboardApi.status();
      error = null;
      updateServiceCounts();
    } catch (e) {
      if (!status) {
        error = e instanceof Error ? e.message : '데이터 로드 실패';
      } else {
        console.warn('[ServiceStatus] 폴링 실패 (이전 데이터 유지):', e);
      }
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
      if (!status) {
        error = e instanceof Error ? e.message : '새로고침 실패';
      } else {
        console.warn('[ServiceStatus] 새로고침 실패 (이전 데이터 유지):', e);
      }
    } finally {
      refreshing = false;
    }
  }

  function updateServiceCounts() {
    if (!status || !onStatusChange) return;

    let running = 0;
    let total = 0;
    for (const project of Object.values(status.projects)) {
      for (const service of project.nssm_services) {
        total += 1;
        if (service.status === 'Running') running += 1;
      }
    }
    onStatusChange(running, total);
  }

  async function fetchExtraStatus() {
    try {
      const [runnerStatus, redis, systemStatus] = await Promise.all([
        devRunnerRunnerApi.status().catch(() => null),
        serviceDashboardApi.redisStatus().catch(() => null),
        systemApi.status().catch(() => null)
      ]);
      if (runnerStatus !== null) devRunnerStatus = runnerStatus;
      dbStatus = systemStatus?.db_status ?? null;
      redisStatus = redis ?? {
        connected: false,
        container_running: null,
        uptime_seconds: null,
        used_memory_mb: null,
        connected_clients: null
      };
    } catch {
      // graceful
    }
  }

  async function fetchProcessWatch() {
    if (processWatchInFlight) return;
    processWatchInFlight = true;
    try {
      const [latest, history] = await Promise.all([
        processWatchApi.latest({ min_mb: 0, limit: 200 }),
        processWatchApi.history({ min_mb: 1024, limit: 200 })
      ]);
      processWatchLatest = latest;
      processWatchRows = latest.items;
      processWatchHistoryRows = history.items;
      updateProcessDeltaRates(latest.items);
      processWatchError = latest.error ?? null;
    } catch (e) {
      processWatchError = e instanceof Error ? e.message : 'process-watch 조회 실패';
    } finally {
      processWatchInFlight = false;
    }
  }

  function clearProcessPollingInterval() {
    if (!processPollingInterval) return;
    clearInterval(processPollingInterval);
    processPollingInterval = null;
  }

  function toggleProcessPolling() {
    processPollingEnabled = !processPollingEnabled;
    if (processPollingEnabled) {
      processLoading = true;
      fetchProcessWatch().finally(() => {
        processLoading = false;
      });
      clearProcessPollingInterval();
      processPollingInterval = setInterval(() => {
        void fetchProcessWatch();
      }, PROCESS_REFRESH_INTERVAL);
    } else {
      clearProcessPollingInterval();
    }
  }

  function requestKillProcess(item: ProcessWatchItem) {
    const scope = item.scope ?? 'external';
    killDialogItem = item;
    killReasonDefault = scope === 'monitor_page'
      ? 'memory pressure cleanup'
      : 'external process emergency cleanup';
    killDialogOpen = true;
  }

  function cancelKillProcess() {
    killDialogOpen = false;
    killDialogItem = null;
    killReasonDefault = '';
  }

  async function confirmKillProcess(reason: string) {
    const trimmedReason = reason.trim();
    const item = killDialogItem;
    if (!item) return;

    if (trimmedReason.length < 8) {
      toast.error('종료 사유는 최소 8자 이상이어야 합니다.');
      return;
    }

    showConfirm(
      '프로세스 강제 종료',
      `PID ${item.pid} (${item.name})을 강제 종료하시겠습니까?`,
      async () => {
        try {
          await processWatchApi.kill({
            pid: item.pid,
            expected_create_time: item.create_time,
            expected_cmdline_hash: item.cmdline_hash,
            reason: trimmedReason,
            force: (item.scope ?? 'external') !== 'monitor_page'
          });
          await fetchProcessWatch();
        } catch (e) {
          console.error('프로세스 종료 실패:', e);
          toast.error(`프로세스 종료 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
        }
      },
      true,
      '강제 종료'
    );
    killDialogItem = null;
    killReasonDefault = '';
  }

  async function fetchCleanupStats() {
    cleanupStatsLoading = true;
    try {
      cleanupStats = await serviceDashboardApi.nightlyCleanupStats(14);
    } catch (e) {
      console.error('Failed to fetch cleanup stats:', e);
    } finally {
      cleanupStatsLoading = false;
    }
  }

  function resetSelfRestartState() {
    selfRestartState = 'idle';
    selfRestartMessage = '';
  }

  async function pollApiReadyByPort(
    port: number,
    maxPoll: number,
    intervalMs: number,
    label: string
  ): Promise<boolean> {
    const startTime = Date.now();
    for (let i = 1; i <= maxPoll; i += 1) {
      let isReady = false;
      try {
        const checkUrl = `http://${location.hostname}:${port}/api/v1/ready`;
        const response = await fetch(checkUrl);
        const payload = response.ok ? await response.json().catch(() => null) : null;
        isReady = payload?.ready === true;
      } catch {
        isReady = false;
      }

      if (isReady) return true;

      const elapsed = Math.round((Date.now() - startTime) / 1000);
      selfRestartMessage = `${label} 응답 대기 중... ${elapsed}초 (${i}/${maxPoll})`;

      if (i < maxPoll) {
        await sleep(intervalMs);
      }
    }

    return false;
  }

  async function selfRestartApi(port: number, label: string) {
    const isSelf = (location.port === '6101' && port === 8001) || (location.port === '6100' && port === 8000);
    const initialWaitMs = isSelf ? SELF_RESTART_INITIAL_WAIT_SELF : SELF_RESTART_INITIAL_WAIT_REMOTE;

    selfRestartState = 'requested';
    selfRestartMessage = `${label} Self-restart 요청 중...`;

    try {
      await systemApi.closeApiGate(port, 'UI self-restart');
      const response = await systemApi.selfRestartByPort(port, 2.0);
      selfRestartState = 'waiting';
      selfRestartMessage = `${label} PID ${response.pid} 종료 대기 중...`;
    } catch (e) {
      if (!isSelf) {
        selfRestartState = 'failed';
        selfRestartMessage = `${label} 요청 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`;
        return;
      }
      selfRestartState = 'waiting';
      selfRestartMessage = `${label} 연결 끊김 (정상) - 재시작 대기 중...`;
    }

    await sleep(initialWaitMs);

    selfRestartState = 'checking';
    selfRestartMessage = `${label} 재시작 확인 중...`;

    const success = await pollApiReadyByPort(
      port,
      SELF_RESTART_MAX_POLL,
      SELF_RESTART_POLL_INTERVAL,
      label
    );

    if (success) {
      selfRestartState = 'done';
      selfRestartMessage = `${label} 재시작 완료`;
      await fetchStatus();
      setTimeout(() => {
        resetSelfRestartState();
      }, 3000);
    } else {
      selfRestartState = 'failed';
      selfRestartMessage = `${label} 재시작 확인 실패 (3분 초과). 수동 확인 필요.`;
    }
  }

  async function openApiGateManually() {
    await fetch('/__local/api-gate/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'manual service status open' })
    });
    await apiGate.refreshStatus();
  }

  onMount(() => {
    fetchStatus();
    fetchExtraStatus();
    fetchCleanupStats();

    const interval = setInterval(() => {
      if (selfRestartState !== 'idle') return;
      void fetchStatus();
      void fetchExtraStatus();
    }, REFRESH_INTERVAL);

    return () => {
      clearInterval(interval);
      clearProcessPollingInterval();
    };
  });
</script>

<ConfirmDialog
  bind:open={confirmDialog.open}
  title={confirmDialog.title}
  description={confirmDialog.description}
  confirmText={confirmDialog.confirmText}
  destructive={confirmDialog.destructive}
  onConfirm={confirmDialog.action}
  onCancel={() => {}}
/>

<ProcessKillReasonDialog
  bind:open={killDialogOpen}
  item={killDialogItem}
  defaultReason={killReasonDefault}
  onConfirm={confirmKillProcess}
  onCancel={cancelKillProcess}
/>

<div class="space-y-4 max-w-6xl mx-auto">
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
    <div class="bg-card rounded-lg border border-border shadow-card p-3 flex flex-wrap items-center gap-3">
      <span class="text-sm font-medium text-foreground">API 게이트</span>
      <span
        class="px-2 py-0.5 text-xs rounded font-medium"
        class:bg-success-light={apiGate.state === 'open'}
        class:text-success={apiGate.state === 'open'}
        class:bg-warning-light={apiGate.state !== 'open'}
        class:text-warning-foreground={apiGate.state !== 'open'}
      >
        {apiGate.state}
      </span>
      {#if apiGate.reason}
        <span class="text-xs text-muted-foreground">{apiGate.reason}</span>
      {/if}
      {#if apiGate.state !== 'open'}
        <button
          onclick={openApiGateManually}
          class="ml-auto h-8 px-3 text-xs rounded-md font-medium bg-primary text-white hover:bg-primary-hover transition-colors"
        >
          게이트 열기
        </button>
      {/if}
    </div>

    <ServiceDashboardSection
      {status}
      {refreshing}
      {runningServices}
      {allServices}
      {healthyWorkers}
      {allWorkers}
      {allTasks}
      {allStartups}
      {taskErrors}
      {servicesByProject}
      {tasksByFolder}
      {workerTierProcs}
      {infraTierProcs}
      {redisStatus}
      {dbStatus}
      {devRunnerStatus}
      {selfRestartState}
      {selfRestartMessage}
      {restartSteps}
      {stepStatus}
      {actionLoading}
      {formatCollectedAt}
      {formatDateTime}
      {formatUptime}
      {serviceVariant}
      {workerVariant}
      {workerStatusText}
      {workerStatusTextClass}
      {taskVariant}
      {showConfirm}
      {fetchStatus}
      {refreshStatus}
      {selfRestartApi}
      {resetSelfRestartState}
      {actions}
    />
  {:else}
    <div class="bg-card rounded-lg border border-border shadow-card p-8 text-center">
      <p class="text-muted-foreground mb-3">서비스 정보가 없습니다.</p>
      <button
        onclick={refreshStatus}
        disabled={refreshing}
        class="h-9 px-4 text-sm rounded-md font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        즉시 수집
      </button>
    </div>
  {/if}

  <ProcessWatchSection
    {processPollingEnabled}
    {processWatchLatest}
    {processWatchRows}
    {processWatchHistoryRows}
    {processWatchError}
    {processLoading}
    {toggleProcessPolling}
    {fetchProcessWatch}
    {requestKillProcess}
    {getProcessDeltaRate}
    {formatProcessDelta}
    {processDeltaTextClass}
    {formatProcessUptime}
    {formatProcessStart}
    {formatAncestorChain}
    {processWatchKey}
  />

  <CleanupStatsSection {cleanupStats} {cleanupStatsLoading} />

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
