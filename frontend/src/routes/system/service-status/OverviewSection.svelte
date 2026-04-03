<script lang="ts">
  import StatusDot from '$lib/components/ui/StatusDot.svelte';
  import type { OverviewSectionProps } from './types';

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
    formatCollectedAt,
    fetchStatus,
    refreshStatus
  }: OverviewSectionProps = $props();
</script>

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
        class="h-8 px-3 text-xs rounded-md font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {refreshing ? '수집 중...' : '즉시 수집'}
      </button>
    </div>
  </div>

  <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
    <div class="flex items-center gap-3 p-3 rounded-lg bg-muted/40">
      <div class="flex items-center justify-center h-9 w-9 rounded-md {runningServices === allServices.length ? 'bg-success-light' : 'bg-warning-light'}">
        <StatusDot variant={runningServices === allServices.length ? 'success' : 'warning'} size="md" pulse={runningServices === allServices.length} />
      </div>
      <div>
        <div class="text-xs text-muted-foreground">NSSM 서비스</div>
        <div class="text-lg font-semibold font-mono">{runningServices}<span class="text-sm text-muted-foreground font-normal">/{allServices.length}</span></div>
      </div>
    </div>

    <div class="flex items-center gap-3 p-3 rounded-lg bg-muted/40">
      <div class="flex items-center justify-center h-9 w-9 rounded-md {healthyWorkers === allWorkers.length ? 'bg-success-light' : 'bg-warning-light'}">
        <StatusDot variant={healthyWorkers === allWorkers.length ? 'success' : 'warning'} size="md" pulse={healthyWorkers === allWorkers.length} />
      </div>
      <div>
        <div class="text-xs text-muted-foreground">워커 프로세스</div>
        <div class="text-lg font-semibold font-mono">{healthyWorkers}<span class="text-sm text-muted-foreground font-normal">/{allWorkers.length}</span></div>
      </div>
    </div>

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

  <div class="flex items-center gap-2 text-xs text-muted-foreground">
    <StatusDot variant="success" size="sm" pulse />
    <span>자동 갱신 30초</span>
    <span class="mx-1">·</span>
    <span>마지막 수집: {formatCollectedAt(status.collected_at)}</span>
  </div>
</div>
