<script lang="ts">
  import type {
    ServiceDashboardStatus,
    RedisStatus,
    NssmService,
    WorkerProcess,
    ScheduledTask,
    StartupProgram
  } from '$lib/api';
  import type { RunStatusResponse } from '$lib/api/dev-runner';
  import OverviewSection from './OverviewSection.svelte';
  import ServicesSection from './ServicesSection.svelte';
  import WorkersSection from './WorkersSection.svelte';
  import TasksSection from './TasksSection.svelte';
  import InfrastructureSection from './InfrastructureSection.svelte';
  import type {
    ConfirmAction,
    DbCircuitStatus,
    RedisFetchState,
    RestartStep,
    ServiceDashboardActions,
    WorkerStatusVariant
  } from './types';

  interface Props {
    status: ServiceDashboardStatus;
    refreshing: boolean;
    runningServices: number;
    allServices: NssmService[];
    healthyWorkers: number;
    allWorkers: WorkerProcess[];
    allTasks: ScheduledTask[];
    allStartups: StartupProgram[];
    taskErrors: number;
    servicesByProject: Record<string, NssmService[]>;
    tasksByFolder: Record<string, ScheduledTask[]>;
    workerTierProcs: WorkerProcess[];
    infraTierProcs: WorkerProcess[];
    redisStatus: RedisStatus | null;
    redisFetchState: RedisFetchState;
    dbStatus: DbCircuitStatus | null;
    devRunnerStatus: RunStatusResponse | null;
    selfRestartState: 'idle' | 'requested' | 'waiting' | 'checking' | 'done' | 'failed';
    selfRestartMessage: string;
    restartSteps: readonly RestartStep[];
    stepStatus: (stepKey: 'requested' | 'waiting' | 'checking' | 'done') => 'active' | 'done' | 'pending' | 'failed';
    actionLoading: string | null;
    formatCollectedAt: (isoString: string | null) => string;
    formatDateTime: (isoString: string | null) => string;
    formatUptime: (seconds: number | null) => string;
    serviceVariant: (svc: NssmService) => 'success' | 'warning' | 'error' | 'gray';
    workerVariant: (worker: WorkerProcess) => 'success' | 'warning' | 'error' | 'gray';
    workerStatusText: (worker: WorkerProcess) => { text: string; variant: WorkerStatusVariant };
    workerStatusTextClass: (variant: WorkerStatusVariant) => string;
    taskVariant: (state: string) => 'success' | 'warning' | 'gray';
    showConfirm: (
      title: string,
      description: string,
      action: ConfirmAction,
      destructive?: boolean,
      confirmText?: string
    ) => void;
    fetchStatus: () => void | Promise<void>;
    refreshStatus: () => void | Promise<void>;
    selfRestartApi: (port: number, label: string) => Promise<void>;
    resetSelfRestartState: () => void;
    actions: ServiceDashboardActions;
  }

  let {
    status,
    refreshing,
    runningServices,
    allServices,
    healthyWorkers,
    allWorkers,
    allTasks,
    allStartups,
    taskErrors,
    servicesByProject,
    tasksByFolder,
    workerTierProcs,
    infraTierProcs,
    redisStatus,
    redisFetchState,
    dbStatus,
    devRunnerStatus,
    selfRestartState,
    selfRestartMessage,
    restartSteps,
    stepStatus,
    actionLoading,
    formatCollectedAt,
    formatDateTime,
    formatUptime,
    serviceVariant,
    workerVariant,
    workerStatusText,
    workerStatusTextClass,
    taskVariant,
    showConfirm,
    fetchStatus,
    refreshStatus,
    selfRestartApi,
    resetSelfRestartState,
    actions
  }: Props = $props();
</script>

<OverviewSection
  {status}
  {refreshing}
  {runningServices}
  {allServices}
  {healthyWorkers}
  {allWorkers}
  {allTasks}
  {allStartups}
  {taskErrors}
  {formatCollectedAt}
  {fetchStatus}
  {refreshStatus}
/>

<div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
  <ServicesSection
    {allServices}
    {servicesByProject}
    {selfRestartState}
    {selfRestartMessage}
    {restartSteps}
    {stepStatus}
    {actionLoading}
    {serviceVariant}
    {showConfirm}
    {selfRestartApi}
    {resetSelfRestartState}
    stopService={actions.stopService}
    startService={actions.startService}
  />

  <WorkersSection
    {allWorkers}
    {workerTierProcs}
    {infraTierProcs}
    {redisStatus}
    {actionLoading}
    {workerVariant}
    {workerStatusText}
    {workerStatusTextClass}
    {showConfirm}
    restartWorkers={actions.restartWorkers}
    stopWatchdogs={actions.stopWatchdogs}
    startWatchdogs={actions.startWatchdogs}
    restartSingleWorker={actions.restartSingleWorker}
    restartInfra={actions.restartInfra}
  />
</div>

<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
  <TasksSection
    {allTasks}
    {tasksByFolder}
    {actionLoading}
    {formatDateTime}
    {taskVariant}
    {showConfirm}
    runTask={actions.runTask}
    removeTask={actions.removeTask}
  />

  <InfrastructureSection
    {redisStatus}
    {redisFetchState}
    {dbStatus}
    {devRunnerStatus}
    {allStartups}
    {actionLoading}
    {formatUptime}
    {formatCollectedAt}
    {showConfirm}
    restartRedis={actions.restartRedis}
    restartDevRunner={actions.restartDevRunner}
    stopDevRunner={actions.stopDevRunner}
    resetDevRunner={actions.resetDevRunner}
    startDevRunner={actions.startDevRunner}
    removeStartup={actions.removeStartup}
    restartCommandListener={actions.restartCommandListener}
  />
</div>
