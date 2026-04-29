import type { NssmService, ProcessWatchItem, ScheduledTask, WorkerProcess } from '$lib/api';
import type { SectionVariant, WorkerStatusInfo, WorkerStatusVariant } from './types';

export function groupBy<T extends { project: string }>(items: T[]): Record<string, T[]> {
  const groups: Record<string, T[]> = {};
  for (const item of items) {
    (groups[item.project] ??= []).push(item);
  }
  return groups;
}

export function groupTasksByFolder(tasks: ScheduledTask[]): Record<string, ScheduledTask[]> {
  const groups: Record<string, ScheduledTask[]> = {};
  for (const task of tasks) {
    (groups[task.Folder] ??= []).push(task);
  }
  return groups;
}

export function formatCollectedAt(isoString: string | null): string {
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

export function formatDateTime(isoString: string | null): string {
  if (!isoString) return '-';
  try {
    const date = new Date(isoString);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    if (isToday) {
      return `오늘 ${date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`;
    }
    return `${date.getMonth() + 1}월 ${date.getDate()}일 ${date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`;
  } catch {
    return isoString;
  }
}

export function formatUptime(seconds: number | null): string {
  if (seconds === null) return '-';
  if (seconds < 60) return `${seconds}초`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}시간 ${m}분`;
}

export function serviceVariant(svc: NssmService): SectionVariant {
  if (svc.status === 'Unregistered') return 'error';
  if (svc.status === 'Running' && svc.frontend_health && svc.frontend_health !== 'healthy') return 'warning';
  if (svc.status === 'Running') return 'success';
  if (svc.status === 'StartPending' || svc.status === 'StopPending') return 'warning';
  return 'error';
}

export function workerVariant(worker: WorkerProcess): SectionVariant {
  const hasWatchdog = worker.watchdog !== null && worker.watchdog !== undefined;
  const wd = worker.watchdog?.running ?? false;
  const wk = worker.worker?.running ?? false;

  if (!hasWatchdog) return wk ? 'success' : 'gray';
  if (wd && wk) return 'success';
  if (wd && !wk) return 'warning';
  return 'error';
}

export function workerStatusText(worker: WorkerProcess): WorkerStatusInfo {
  const hasWatchdog = worker.watchdog !== null && worker.watchdog !== undefined;
  const wd = worker.watchdog?.running ?? false;
  const wk = worker.worker?.running ?? false;

  if (!hasWatchdog) return wk ? { text: '정상', variant: 'success' } : { text: '중지됨', variant: 'error' };
  if (wd && wk) return { text: '정상', variant: 'success' };
  if (wd && !wk) return { text: '워커 중지', variant: 'warning' };
  if (!wd && wk) return { text: 'WD 없음', variant: 'warning' };
  return { text: '중지됨', variant: 'error' };
}

export function workerStatusTextClass(variant: WorkerStatusVariant): string {
  if (variant === 'success') return 'text-success';
  if (variant === 'warning') return 'text-warning';
  return 'text-error';
}

export function taskVariant(state: string): Extract<SectionVariant, 'success' | 'warning' | 'gray'> {
  if (state === 'Ready') return 'success';
  if (state === 'Running') return 'warning';
  return 'gray';
}

export function processWatchKey(proc: ProcessWatchItem): string {
  return `${proc.pid}:${proc.cmdline_hash || ''}`;
}

export function formatProcessDelta(rate: number | null): string {
  if (rate === null) return '-';
  const sign = rate > 0 ? '+' : '';
  return `${sign}${rate.toFixed(1)} MB/s`;
}
