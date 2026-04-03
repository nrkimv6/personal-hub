<script lang="ts">
  import StatusDot from '$lib/components/ui/StatusDot.svelte';
  import type { WorkersSectionProps } from './types';

  let {
    allWorkers,
    workerTierProcs,
    infraTierProcs,
    redisStatus,
    actionLoading,
    workerVariant,
    workerStatusText,
    workerStatusTextClass,
    showConfirm,
    restartWorkers,
    stopWatchdogs,
    startWatchdogs,
    restartSingleWorker,
    restartInfra
  }: WorkersSectionProps = $props();
</script>

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
        class="h-7 px-2 text-[11px] rounded-md font-medium border border-input bg-background hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        전체 재시작
      </button>
      <button
        onclick={() => showConfirm('Watchdog 중지', '모든 watchdog를 중지합니다. 워커가 죽어도 자동 재시작되지 않습니다.', stopWatchdogs, true, '중지')}
        disabled={actionLoading === 'watchdogs-stop'}
        class="h-7 px-2 text-[11px] rounded-md font-medium text-warning border border-warning/30 bg-warning-light hover:bg-warning/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        WD 중지
      </button>
      <button
        onclick={() => startWatchdogs()}
        disabled={actionLoading === 'watchdogs-start'}
        class="h-7 px-2 text-[11px] rounded-md font-medium text-success border border-success/30 bg-success-light hover:bg-success/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        title={redisStatus && !redisStatus.connected ? 'Redis 연결 필요' : ''}
      >
        WD 시작
      </button>
    </div>
  </div>

  {#each workerTierProcs as proc}
    {@const ws = workerStatusText(proc)}
    <div class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 rounded transition-colors">
      <StatusDot variant={workerVariant(proc)} size="sm" pulse={workerVariant(proc) === 'success'} />
      <span class="font-medium text-sm text-foreground">{proc.label}</span>
      <span class="font-mono text-[11px] text-muted-foreground hidden sm:inline">{proc.name}</span>

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

        <span class="text-[11px] font-medium {workerStatusTextClass(ws.variant)}">{ws.text}</span>

        {#if proc.worker}
          <button
            onclick={() => showConfirm('워커 재시작', `"${proc.label}" 워커를 재시작합니다.`, () => restartSingleWorker(proc.name))}
            disabled={actionLoading === `worker-${proc.name}`}
            class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            재시작
          </button>
        {/if}
      </div>
    </div>
  {/each}

  {#if infraTierProcs.length > 0}
    <div class="border-t border-border mt-2 pt-2">
      <span class="text-xs text-muted-foreground px-3">인프라</span>
      {#each infraTierProcs as proc}
        {@const ws = workerStatusText(proc)}
        <div class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 rounded transition-colors">
          <StatusDot variant={workerVariant(proc)} size="sm" pulse={workerVariant(proc) === 'success'} />
          <span class="font-medium text-sm text-foreground">{proc.label}</span>
          <span class="font-mono text-[11px] text-muted-foreground hidden sm:inline">{proc.name}</span>

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

            <span class="text-[11px] font-medium {workerStatusTextClass(ws.variant)}">{ws.text}</span>

            <button
              onclick={() => showConfirm('인프라 재시작', `"${proc.label}" 인프라를 재시작합니다.`, () => restartInfra(proc.name))}
              disabled={actionLoading === `infra-${proc.name}`}
              class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              재시작
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}

  {#if allWorkers.length === 0}
    <p class="text-sm text-muted-foreground py-4 text-center">워커 정보가 없습니다.</p>
  {/if}
</div>
