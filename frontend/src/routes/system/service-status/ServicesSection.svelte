<script lang="ts">
  import StatusDot from '$lib/components/ui/StatusDot.svelte';
  import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
  import type { ServicesSectionProps } from './types';

  let {
    allServices,
    servicesByProject,
    selfRestartState,
    selfRestartMessage,
    restartSteps,
    stepStatus,
    actionLoading,
    serviceVariant,
    showConfirm,
    selfRestartApi,
    resetSelfRestartState,
    stopService,
    startService
  }: ServicesSectionProps = $props();
</script>

<div class="bg-card rounded-lg border border-border shadow-card p-4">
  <div class="flex items-center justify-between mb-3">
    <div class="flex items-center gap-2">
      <h3 class="text-sm font-semibold text-foreground">Windows 서비스</h3>
      <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">{allServices.length}</span>
    </div>
    <div class="flex gap-1">
      <button
        onclick={() => showConfirm('Dev API 재시작', 'Dev API(:8001)를 재시작합니다. 약 15초간 중단됩니다.', () => selfRestartApi(8001, 'Dev'), true, '재시작')}
        disabled={selfRestartState !== 'idle'}
        class="h-7 px-2 text-[11px] rounded-md font-medium border border-input bg-background hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        Dev 재시작
      </button>
      <button
        onclick={() => showConfirm('Prod API 재시작', 'Prod API(:8000)를 재시작합니다. 약 15초간 중단됩니다.', () => selfRestartApi(8000, 'Prod'), true, '재시작')}
        disabled={selfRestartState !== 'idle'}
        class="h-7 px-2 text-[11px] rounded-md font-medium border border-input bg-background hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        Prod 재시작
      </button>
    </div>
  </div>

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
          <button onclick={resetSelfRestartState} class="text-xs text-error underline ml-auto">닫기</button>
        {/if}
      </div>
    </div>
  {/if}

  {#each Object.entries(servicesByProject) as [project, services]}
    <div class="mb-2 last:mb-0">
      <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-3 py-1">{project}</div>
      {#each services as svc}
        <div class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 rounded transition-colors">
          <StatusDot variant={serviceVariant(svc)} size="sm" pulse={svc.status === 'Running'} />
          <span class="font-medium text-sm text-foreground truncate">{svc.display_name}</span>
          <span class="font-mono text-[11px] text-muted-foreground truncate hidden sm:inline">{svc.name}</span>
          <div class="ml-auto flex items-center gap-2 shrink-0">
            <StatusBadge variant={serviceVariant(svc)} size="sm">{svc.status === 'Unregistered' ? '미등록' : svc.status}</StatusBadge>
            {#if svc.frontend_health && svc.frontend_health !== 'healthy'}
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-warning/10 text-warning font-medium">
                6100 down{svc.degraded_reason ? ` (${svc.degraded_reason})` : ''}
              </span>
            {/if}
            <span class="text-[10px] text-muted-foreground">{svc.start_type}</span>
            {#if svc.status === 'Running'}
              <button
                onclick={() => showConfirm('서비스 중지', `"${svc.display_name}" 서비스를 중지합니다.`, () => stopService(svc.name), true, '중지')}
                disabled={actionLoading?.startsWith('nssm-')}
                class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-error hover:bg-error-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="중지"
                aria-label="서비스 중지"
              >
                <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" rx="1"/></svg>
              </button>
            {:else}
              <button
                onclick={() => startService(svc.name)}
                disabled={actionLoading?.startsWith('nssm-')}
                class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-success hover:bg-success-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="시작"
                aria-label="서비스 시작"
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
