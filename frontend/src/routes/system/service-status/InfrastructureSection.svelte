<script lang="ts">
  import StatusDot from '$lib/components/ui/StatusDot.svelte';
  import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
  import type { InfrastructureSectionProps } from './types';

  let {
    redisStatus,
    dbStatus,
    devRunnerStatus,
    allStartups,
    actionLoading,
    formatUptime,
    formatCollectedAt,
    showConfirm,
    restartRedis,
    restartDevRunner,
    stopDevRunner,
    resetDevRunner,
    startDevRunner,
    removeStartup,
    restartCommandListener
  }: InfrastructureSectionProps = $props();

  const dbVariant = (state: string | undefined): 'success' | 'warning' | 'error' => {
    if (state === 'open') return 'error';
    if (state === 'half_open') return 'warning';
    return 'success';
  };

  const dbLabel = (state: string | undefined) => {
    if (state === 'open') return 'DB 장애';
    if (state === 'half_open') return '복구 확인 중';
    return '정상';
  };
</script>

<div class="bg-card rounded-lg border border-border shadow-card p-4">
  <h3 class="text-sm font-semibold text-foreground mb-3">인프라</h3>

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
          class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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

  {#if dbStatus}
    <div class="mb-3 pb-3 border-b border-border">
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-2">
          <StatusDot
            variant={dbVariant(dbStatus.state)}
            size="md"
            pulse={dbStatus.state === 'closed'}
          />
          <span class="font-medium text-sm">Database</span>
          <StatusBadge variant={dbVariant(dbStatus.state)} size="sm">
            {dbLabel(dbStatus.state)}
          </StatusBadge>
        </div>
      </div>
      <div class="flex gap-3 text-[10px] text-muted-foreground px-1">
        <span>State: {dbStatus.state}</span>
        <span>Failures: {dbStatus.fail_count}</span>
      </div>
      {#if dbStatus.last_failure_iso}
        <div class="text-[10px] text-muted-foreground px-1">
          Last failure: {formatCollectedAt(dbStatus.last_failure_iso)}
        </div>
      {/if}
    </div>
  {/if}

  {#if devRunnerStatus}
    <div class="mb-3 pb-3 border-b border-border">
      <div class="flex items-center justify-between mb-2">
        <div class="flex items-center gap-2">
          <StatusDot
            variant={devRunnerStatus.running ? 'success' : devRunnerStatus.crashed ? 'error' : 'gray'}
            size="md"
            pulse={devRunnerStatus.running}
          />
          <span class="font-medium text-sm">Dev Runner</span>
          <StatusBadge
            variant={devRunnerStatus.running ? 'success' : devRunnerStatus.crashed ? 'error' : 'gray'}
            size="sm"
          >
            {devRunnerStatus.running ? 'Running' : devRunnerStatus.crashed ? 'Crashed' : 'Stopped'}
          </StatusBadge>
        </div>
        <div class="flex gap-1">
          {#if devRunnerStatus.running}
            <button
              onclick={() => showConfirm('Dev Runner 재시작', 'Dev Runner를 재시작합니다.', restartDevRunner, false, '재시작')}
              disabled={actionLoading === 'dev-runner-restart'}
              class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              재시작
            </button>
            <button
              onclick={() => showConfirm('Dev Runner 중지', 'Dev Runner를 중지합니다.', stopDevRunner, true, '중지')}
              disabled={actionLoading === 'dev-runner-stop'}
              class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              중지
            </button>
          {:else if devRunnerStatus.crashed}
            <button
              onclick={() => showConfirm('Dev Runner 리셋', 'RUNNING → PENDING 상태로 리셋합니다.', resetDevRunner)}
              disabled={actionLoading === 'dev-runner-reset'}
              class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              리셋
            </button>
          {:else}
            <button
              onclick={() => showConfirm('Dev Runner 시작', 'Dev Runner를 시작합니다.', startDevRunner, false, '시작')}
              disabled={actionLoading === 'dev-runner-start'}
              class="h-6 px-1.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              시작
            </button>
          {/if}
        </div>
      </div>
      {#if devRunnerStatus.pid}
        <div class="text-[10px] text-muted-foreground px-1">PID: {devRunnerStatus.pid}</div>
      {/if}
      {#if devRunnerStatus.plan_file}
        <div class="text-[10px] text-muted-foreground px-1 truncate" title={devRunnerStatus.plan_file}>
          {devRunnerStatus.plan_file}
        </div>
      {/if}
      {#if devRunnerStatus.running && devRunnerStatus.start_time}
        <div class="text-[10px] text-muted-foreground px-1">시작: {formatCollectedAt(devRunnerStatus.start_time)}</div>
      {/if}
      {#if !devRunnerStatus.running && !devRunnerStatus.redis_connected}
        <div class="mt-1 text-[10px] text-error px-1 flex items-center gap-1">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/><line x1="12" y1="8" x2="12" y2="12" stroke-width="2"/><line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2"/></svg>
          Redis 미연결
        </div>
      {:else if !devRunnerStatus.running && !devRunnerStatus.listener_alive && devRunnerStatus.redis_connected}
        <div class="mt-1 text-[10px] text-warning px-1 flex items-center gap-1">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/><line x1="12" y1="8" x2="12" y2="12" stroke-width="2"/><line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2"/></svg>
          Command Listener 미실행
          <button
            onclick={() => restartCommandListener()}
            disabled={actionLoading === 'restart-listener'}
            class="ml-1 h-4 px-1 text-[9px] rounded border border-warning text-warning hover:bg-warning hover:text-warning-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >재시작</button>
        </div>
      {/if}
    </div>
  {/if}

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
          class="ml-auto h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-error hover:bg-error-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
          title="제거"
          aria-label="시작프로그램 제거"
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
