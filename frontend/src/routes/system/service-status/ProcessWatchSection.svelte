<script lang="ts">
  import type { ProcessWatchSectionProps } from './types';

  let {
    processPollingEnabled,
    processWatchLatest,
    processWatchRows,
    processWatchHistoryRows,
    processWatchError,
    processLoading,
    toggleProcessPolling,
    fetchProcessWatch,
    requestKillProcess,
    getProcessDeltaRate,
    formatProcessDelta,
    processDeltaTextClass,
    formatProcessUptime,
    formatProcessStart,
    formatAncestorChain,
    processWatchKey
  }: ProcessWatchSectionProps = $props();
</script>

<!-- Process Watch 모니터 -->
<div class="bg-card rounded-lg border border-border shadow-card">
  <div class="flex items-center justify-between px-4 py-3 border-b border-border">
    <div class="flex items-center gap-2">
      <h3 class="text-sm font-semibold text-foreground">Process Watch (Python)</h3>
      {#if processPollingEnabled}
        <span class="text-[10px] px-1.5 py-0.5 rounded bg-success-light text-success font-medium">{processWatchRows.length}개</span>
        <span class="text-[10px] text-muted-foreground">5초 갱신</span>
      {/if}
      {#if processWatchLatest}
        <span class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
          source={processWatchLatest.source}
        </span>
        {#if processWatchLatest.snapshot_age_seconds !== null}
          <span class="text-[10px] text-muted-foreground">age {processWatchLatest.snapshot_age_seconds}s</span>
        {/if}
        {#if processWatchLatest.stale}
          <span class="text-[10px] px-1.5 py-0.5 rounded bg-warning-light text-warning">stale</span>
        {/if}
      {/if}
    </div>
    <div class="flex items-center gap-1.5">
      {#if processPollingEnabled}
        <button
          onclick={() => fetchProcessWatch()}
          class="h-6 px-2 text-[11px] rounded border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          aria-label="프로세스 모니터 새로고침"
        >새로고침</button>
      {/if}
      <button
        onclick={toggleProcessPolling}
        class="h-6 px-2 text-[11px] rounded font-medium transition-colors {processPollingEnabled ? 'bg-error-light text-error hover:bg-error hover:text-white' : 'bg-primary text-white hover:bg-primary-hover'}"
      >
        {processPollingEnabled ? '모니터링 중지' : '모니터링 시작'}
      </button>
    </div>
  </div>

  {#if processPollingEnabled}
    {#if processLoading}
      <div class="p-4 text-center text-muted-foreground text-xs">로딩 중...</div>
    {:else if processWatchRows.length === 0}
      <div class="p-4 text-center text-muted-foreground text-xs">Python 프로세스 스냅샷이 없습니다.</div>
    {:else}
      {#if processWatchError}
        <div class="px-4 py-2 text-[11px] text-warning bg-warning-light/20 border-b border-border">
          조회 경고: {processWatchError}
        </div>
      {/if}
      <div class="overflow-x-auto">
        <table class="w-full text-[11px]">
          <thead>
            <tr class="border-b border-border text-muted-foreground">
              <th class="px-3 py-2 text-left font-medium">PID</th>
              <th class="px-3 py-2 text-left font-medium">프로세스</th>
              <th class="px-3 py-2 text-right font-medium">메모리</th>
              <th class="px-3 py-2 text-right font-medium">ΔMB/s</th>
              <th class="px-3 py-2 text-left font-medium">실행시간</th>
              <th class="px-3 py-2 text-left font-medium">조상 체인</th>
              <th class="px-3 py-2 text-left font-medium">scope</th>
              <th class="px-3 py-2 text-center font-medium">종료</th>
            </tr>
          </thead>
          <tbody>
            {#each processWatchRows as proc (processWatchKey(proc))}
              {@const deltaRate = getProcessDeltaRate(proc)}
              <tr class="border-b border-border/50 hover:bg-muted/50 {proc.memory_mb > 512 ? 'bg-warning-light/30' : ''} {proc.memory_mb > 1024 ? 'bg-error-light/30' : ''}">
                <td class="px-3 py-1.5 font-mono text-muted-foreground">{proc.pid}</td>
                <td class="px-3 py-1.5 font-medium text-foreground max-w-[240px] truncate" title={proc.cmdline}>{proc.name}</td>
                <td class="px-3 py-1.5 text-right font-mono {proc.memory_mb > 512 ? 'text-warning font-semibold' : ''} {proc.memory_mb > 1024 ? 'text-error font-semibold' : ''}">{proc.memory_mb.toFixed(1)} MB</td>
                <td class="px-3 py-1.5 text-right">
                  <div class="font-mono {processDeltaTextClass(deltaRate)}">{formatProcessDelta(deltaRate)}</div>
                  {#if deltaRate !== null && deltaRate >= 256}
                    <span class="text-[10px] px-1 py-0.5 rounded bg-error-light text-error">급등</span>
                  {:else if deltaRate !== null && deltaRate >= 128}
                    <span class="text-[10px] px-1 py-0.5 rounded bg-warning-light text-warning">상승</span>
                  {/if}
                </td>
                <td class="px-3 py-1.5">
                  <div class="font-mono text-foreground">{formatProcessUptime(proc)}</div>
                  <div class="text-[10px] text-muted-foreground">{formatProcessStart(proc)}</div>
                </td>
                <td class="px-3 py-1.5">
                  <div class="font-mono text-[10px] text-muted-foreground max-w-[420px] truncate" title={formatAncestorChain(proc)}>
                    {formatAncestorChain(proc)}
                  </div>
                  <div class="text-[10px] text-muted-foreground">
                    PPID {proc.ppid ?? '-'} {proc.parent_name ? `(${proc.parent_name})` : ''}
                  </div>
                  {#if proc.is_orphan}
                    <span class="mt-1 inline-block text-[10px] px-1 py-0.5 rounded bg-error-light text-error">orphan</span>
                  {/if}
                </td>
                <td class="px-3 py-1.5">
                  <span class="text-[10px] px-1.5 py-0.5 rounded {proc.scope === 'monitor_page' ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">{proc.scope}</span>
                </td>
                <td class="px-3 py-1.5 text-center">
                  <button
                    onclick={() => requestKillProcess(proc)}
                    class="h-5 w-5 inline-flex items-center justify-center rounded text-muted-foreground hover:text-error hover:bg-error-light transition-colors"
                    title="강제 종료"
                    aria-label="프로세스 강제 종료"
                  >
                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M6 18L18 6M6 6l12 12"/></svg>
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <div class="px-4 py-3 border-t border-border">
        <div class="text-[11px] font-medium text-muted-foreground mb-2">1GB+ 최근 이력</div>
        {#if processWatchHistoryRows.length === 0}
          <div class="text-[11px] text-muted-foreground">기록 없음</div>
        {:else}
          <div class="space-y-1">
            {#each processWatchHistoryRows.slice(0, 8) as item}
              <div class="text-[11px] text-muted-foreground flex items-center gap-2">
                <span class="font-mono text-foreground">PID {item.pid}</span>
                <span>{item.memory_mb.toFixed(1)}MB</span>
                <span>{formatProcessUptime(item)}</span>
                <span>{item.scope}</span>
                {#if item.is_orphan}<span class="text-error">orphan</span>{/if}
                <span class="truncate max-w-[380px]" title={formatAncestorChain(item)}>{formatAncestorChain(item)}</span>
                <span class="ml-auto">{new Date(item.captured_at).toLocaleTimeString('ko-KR')}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {:else}
    <div class="px-4 py-3 text-[11px] text-muted-foreground">
      '모니터링 시작' 버튼을 누르면 process-watch 최신 스냅샷을 5초마다 조회합니다.
    </div>
  {/if}
</div>
