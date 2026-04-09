import type {
  ServiceDashboardStatus,
  RedisStatus,
  NssmService,
  WorkerProcess,
  ScheduledTask,
  StartupProgram,
  ProcessWatchItem,
  ProcessWatchLatestResponse,
  NightlyCleanupStats
} from '$lib/api';
import type { RunStatusResponse } from '$lib/api/dev-runner';

export type SectionVariant = 'success' | 'warning' | 'error' | 'gray';
export type WorkerStatusVariant = 'success' | 'warning' | 'error';
export type SelfRestartState = 'idle' | 'requested' | 'waiting' | 'checking' | 'done' | 'failed';
export type RestartStepKey = 'requested' | 'waiting' | 'checking' | 'done';

export interface WorkerStatusInfo {
  text: string;
  variant: WorkerStatusVariant;
}

export interface RestartStep {
  key: RestartStepKey;
  label: string;
}

export type ConfirmAction = () => void | Promise<void>;

export interface OverviewSectionProps {
  status: ServiceDashboardStatus;
  refreshing: boolean;
  runningServices: number;
  allServices: NssmService[];
  healthyWorkers: number;
  allWorkers: WorkerProcess[];
  allTasks: ScheduledTask[];
  allStartups: StartupProgram[];
  taskErrors: number;
  formatCollectedAt: (isoString: string | null) => string;
  fetchStatus: () => void | Promise<void>;
  refreshStatus: () => void | Promise<void>;
}

export interface ServicesSectionProps {
  allServices: NssmService[];
  servicesByProject: Record<string, NssmService[]>;
  selfRestartState: SelfRestartState;
  selfRestartMessage: string;
  restartSteps: readonly RestartStep[];
  stepStatus: (stepKey: RestartStepKey) => 'active' | 'done' | 'pending' | 'failed';
  actionLoading: string | null;
  serviceVariant: (svc: NssmService) => SectionVariant;
  showConfirm: (
    title: string,
    description: string,
    action: ConfirmAction,
    destructive?: boolean,
    confirmText?: string
  ) => void;
  selfRestartApi: (port: number, label: string) => Promise<void>;
  resetSelfRestartState: () => void;
  stopService: (name: string) => Promise<void>;
  startService: (name: string) => Promise<void>;
}

export interface WorkersSectionProps {
  allWorkers: WorkerProcess[];
  workerTierProcs: WorkerProcess[];
  infraTierProcs: WorkerProcess[];
  redisStatus: RedisStatus | null;
  actionLoading: string | null;
  workerVariant: (worker: WorkerProcess) => SectionVariant;
  workerStatusText: (worker: WorkerProcess) => WorkerStatusInfo;
  workerStatusTextClass: (variant: WorkerStatusVariant) => string;
  showConfirm: (
    title: string,
    description: string,
    action: ConfirmAction,
    destructive?: boolean,
    confirmText?: string
  ) => void;
  restartWorkers: () => Promise<void>;
  stopWatchdogs: () => Promise<void>;
  startWatchdogs: () => Promise<void>;
  restartSingleWorker: (name: string) => Promise<void>;
  restartInfra: (name: string) => Promise<void>;
}

export interface TasksSectionProps {
  allTasks: ScheduledTask[];
  tasksByFolder: Record<string, ScheduledTask[]>;
  actionLoading: string | null;
  formatDateTime: (isoString: string | null) => string;
  taskVariant: (state: string) => Extract<SectionVariant, 'success' | 'warning' | 'gray'>;
  showConfirm: (
    title: string,
    description: string,
    action: ConfirmAction,
    destructive?: boolean,
    confirmText?: string
  ) => void;
  runTask: (folder: string, name: string) => Promise<void>;
  removeTask: (folder: string, name: string) => Promise<void>;
}

export interface InfrastructureSectionProps {
  redisStatus: RedisStatus | null;
  devRunnerStatus: RunStatusResponse | null;
  allStartups: StartupProgram[];
  actionLoading: string | null;
  formatUptime: (seconds: number | null) => string;
  formatCollectedAt: (isoString: string | null) => string;
  showConfirm: (
    title: string,
    description: string,
    action: ConfirmAction,
    destructive?: boolean,
    confirmText?: string
  ) => void;
  restartRedis: () => Promise<void>;
  restartDevRunner: () => Promise<void>;
  stopDevRunner: () => Promise<void>;
  resetDevRunner: () => Promise<void>;
  startDevRunner: () => Promise<void>;
  removeStartup: (name: string) => Promise<void>;
  restartCommandListener: () => Promise<void>;
}

export interface ProcessWatchSectionProps {
  processPollingEnabled: boolean;
  processWatchLatest: ProcessWatchLatestResponse | null;
  processWatchRows: ProcessWatchItem[];
  processWatchHistoryRows: ProcessWatchItem[];
  processWatchError: string | null;
  processLoading: boolean;
  toggleProcessPolling: () => void;
  fetchProcessWatch: () => Promise<void>;
  handleKillProcess: (item: ProcessWatchItem) => Promise<void>;
  getProcessDeltaRate: (proc: ProcessWatchItem) => number | null;
  formatProcessDelta: (rate: number | null) => string;
  processDeltaTextClass: (rate: number | null) => string;
  formatProcessUptime: (proc: ProcessWatchItem) => string;
  formatProcessStart: (proc: ProcessWatchItem) => string;
  formatAncestorChain: (proc: ProcessWatchItem) => string;
  processWatchKey: (proc: ProcessWatchItem) => string;
}

export interface CleanupStatsSectionProps {
  cleanupStats: NightlyCleanupStats | null;
  cleanupStatsLoading: boolean;
}
