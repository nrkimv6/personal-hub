<script lang="ts">
  import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
  import type { TasksSectionProps } from './types';

  let {
    allTasks,
    tasksByFolder,
    actionLoading,
    formatDateTime,
    taskVariant,
    showConfirm,
    runTask,
    removeTask
  }: TasksSectionProps = $props();
</script>

<div class="lg:col-span-2 bg-card rounded-lg border border-border shadow-card p-4">
  <div class="flex items-center gap-2 mb-3">
    <h3 class="text-sm font-semibold text-foreground">예약 작업</h3>
    <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">{allTasks.length}</span>
  </div>

  {#each Object.entries(tasksByFolder) as [folder, tasks]}
    <div class="mb-2 last:mb-0">
      <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-3 py-1">{folder}</div>
      {#each tasks as task}
        <div class="flex items-center gap-2 px-3 py-2 hover:bg-muted/50 rounded transition-colors text-sm">
          <span class="font-medium text-foreground truncate" title={task.Description || ''}>{task.Name}</span>

          {#if task.LastResult !== null && task.LastResult !== 0}
            <span class="text-error shrink-0" title="Error: 0x{task.LastResult.toString(16).toUpperCase()}">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="2"/><line x1="12" y1="8" x2="12" y2="12" stroke-width="2"/><line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2"/></svg>
            </span>
          {/if}

          <div class="ml-auto flex items-center gap-2 shrink-0">
            <span class="text-[10px] text-muted-foreground hidden md:inline" title="마지막 실행">{formatDateTime(task.LastRun)}</span>
            <span class="text-[10px] text-foreground hidden lg:inline" title="다음 실행">{formatDateTime(task.NextRun)}</span>
            <StatusBadge variant={taskVariant(task.State)} size="sm">{task.State}</StatusBadge>

            <button
              onclick={() => runTask(task.Folder, task.Name)}
              disabled={actionLoading?.startsWith(`run-${task.Folder}`)}
              class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-primary hover:bg-primary-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="실행"
              aria-label="예약 작업 실행"
            >
              <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 16 16"><path d="M4 2l10 6-10 6V2z"/></svg>
            </button>
            <button
              onclick={() => showConfirm('작업 제거', `예약 작업 "${folder}/${task.Name}"을 제거합니다. (관리자 권한 필요)`, () => removeTask(task.Folder, task.Name), true, '제거')}
              disabled={actionLoading?.startsWith(`task-${task.Folder}`)}
              class="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-error hover:bg-error-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="제거"
              aria-label="예약 작업 제거"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14"/></svg>
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/each}

  {#if allTasks.length === 0}
    <p class="text-sm text-muted-foreground py-4 text-center">예약 작업이 없습니다.</p>
  {/if}
</div>
