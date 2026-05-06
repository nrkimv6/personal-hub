import type { RedisStatus } from '$lib/api';
import type { ServiceDashboardActions } from './types';

type ToastApi = {
  error: (message: string, duration?: number) => unknown;
  success: (message: string, duration?: number) => unknown;
};

type ServiceDashboardApi = {
  stopNssm: (name: string) => Promise<unknown>;
  startNssm: (name: string) => Promise<unknown>;
  removeStartup: (name: string) => Promise<unknown>;
  runTask: (folder: string, name: string) => Promise<unknown>;
  removeTask: (folder: string, name: string) => Promise<unknown>;
  restartWorkers: () => Promise<unknown>;
  restartWorker: (name: string) => Promise<unknown>;
  restartInfra: (name: string) => Promise<unknown>;
  stopWatchdogs: () => Promise<unknown>;
  startWatchdogs: () => Promise<unknown>;
  restartRedis: () => Promise<{ message: string }>;
};

type DevRunnerRunnerApi = {
  stop: (runnerId: string) => Promise<unknown>;
  stopLegacy: () => Promise<unknown>;
  start: (data: Record<string, never>) => Promise<unknown>;
  resetState: () => Promise<unknown>;
  restartListener: () => Promise<unknown>;
};

export interface CreateServiceStatusActionsDeps {
  serviceDashboardApi: ServiceDashboardApi;
  devRunnerRunnerApi: DevRunnerRunnerApi;
  fetchStatus: () => void | Promise<void>;
  fetchExtraStatus: () => void | Promise<void>;
  getRedisStatus: () => RedisStatus | null;
  getDevRunnerRunnerId: () => string | null | undefined;
  setActionLoading: (actionKey: string | null) => void;
  toast: ToastApi;
}

export function createServiceStatusActions({
  serviceDashboardApi,
  devRunnerRunnerApi,
  fetchStatus,
  fetchExtraStatus,
  getRedisStatus,
  getDevRunnerRunnerId,
  setActionLoading,
  toast
}: CreateServiceStatusActionsDeps): ServiceDashboardActions {
  async function runActionWithLoading(
    actionKey: string,
    work: () => Promise<void>,
    onErrorPrefix: string
  ): Promise<void> {
    setActionLoading(actionKey);
    try {
      await work();
    } catch (e) {
      toast.error(`${onErrorPrefix}: ${e instanceof Error ? e.message : '알 수 없는 오류'}`);
    } finally {
      setActionLoading(null);
    }
  }

  async function stopDevRunnerWithFallback() {
    const runnerId = getDevRunnerRunnerId();
    if (runnerId) {
      await devRunnerRunnerApi.stop(runnerId);
      return;
    }
    await devRunnerRunnerApi.stopLegacy();
  }

  return {
    stopService: (name: string) =>
      runActionWithLoading(`nssm-stop-${name}`, async () => {
        await serviceDashboardApi.stopNssm(name);
        await fetchStatus();
      }, '중지 실패'),

    startService: (name: string) =>
      runActionWithLoading(`nssm-start-${name}`, async () => {
        await serviceDashboardApi.startNssm(name);
        await fetchStatus();
      }, '시작 실패'),

    removeStartup: (name: string) =>
      runActionWithLoading(`startup-${name}`, async () => {
        await serviceDashboardApi.removeStartup(name);
        await fetchStatus();
      }, '제거 실패'),

    runTask: (folder: string, name: string) =>
      runActionWithLoading(`run-${folder}-${name}`, async () => {
        await serviceDashboardApi.runTask(folder, name);
        await fetchStatus();
      }, '실행 실패'),

    removeTask: (folder: string, name: string) =>
      runActionWithLoading(`task-${folder}-${name}`, async () => {
        await serviceDashboardApi.removeTask(folder, name);
        await fetchStatus();
      }, '제거 실패'),

    restartWorkers: () =>
      runActionWithLoading('workers', async () => {
        await serviceDashboardApi.restartWorkers();
        await fetchStatus();
      }, '재시작 실패'),

    restartSingleWorker: (name: string) =>
      runActionWithLoading(`worker-${name}`, async () => {
        await serviceDashboardApi.restartWorker(name);
        await fetchStatus();
      }, '재시작 실패'),

    restartInfra: (name: string) =>
      runActionWithLoading(`infra-${name}`, async () => {
        await serviceDashboardApi.restartInfra(name);
        await fetchStatus();
      }, '재시작 실패'),

    stopWatchdogs: () =>
      runActionWithLoading('watchdogs-stop', async () => {
        await serviceDashboardApi.stopWatchdogs();
        await fetchStatus();
      }, '중지 실패'),

    async startWatchdogs() {
      if (getRedisStatus()?.connected === false) {
        toast.error('Redis가 연결되지 않았습니다.\nwatchdog 시작은 Redis Command Listener를 경유합니다.\n\nCLI에서 실행: python scripts/services/browser_workers.py start');
        return;
      }

      await runActionWithLoading('watchdogs-start', async () => {
        await serviceDashboardApi.startWatchdogs();
        await fetchStatus();
      }, '시작 실패\n\nCLI에서 실행: python scripts/services/browser_workers.py start');
    },

    startDevRunner: () =>
      runActionWithLoading('dev-runner-start', async () => {
        await devRunnerRunnerApi.start({});
        await fetchExtraStatus();
      }, '시작 실패'),

    stopDevRunner: () =>
      runActionWithLoading('dev-runner-stop', async () => {
        await stopDevRunnerWithFallback();
        await fetchExtraStatus();
      }, '중지 실패'),

    restartDevRunner: () =>
      runActionWithLoading('dev-runner-restart', async () => {
        await stopDevRunnerWithFallback();
        await devRunnerRunnerApi.start({});
        await fetchExtraStatus();
      }, '재시작 실패'),

    resetDevRunner: () =>
      runActionWithLoading('dev-runner-reset', async () => {
        await devRunnerRunnerApi.resetState();
        await fetchExtraStatus();
      }, '리셋 실패'),

    restartCommandListener: () =>
      runActionWithLoading('restart-listener', async () => {
        await devRunnerRunnerApi.restartListener();
        await fetchExtraStatus();
      }, '리스너 재시작 실패'),

    restartRedis: () =>
      runActionWithLoading('redis-restart', async () => {
        const result = await serviceDashboardApi.restartRedis();
        toast.success(result.message);
        await fetchExtraStatus();
      }, '재시작 실패\n\nCLI: scripts/services/browser_workers.py redis-restart')
  };
}
