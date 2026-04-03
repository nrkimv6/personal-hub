<script lang="ts">
  import type { CleanupStatsSectionProps } from './types';

  let { cleanupStats, cleanupStatsLoading }: CleanupStatsSectionProps = $props();

  let sortedProjectCounts = $derived.by(() => {
    if (!cleanupStats) return [] as Array<[string, number]>;
    return [...Object.entries(cleanupStats.summary.by_project) as Array<[string, number]>].sort((a, b) => b[1] - a[1]);
  });

  let maxProjectCount = $derived.by(() => {
    if (!sortedProjectCounts.length) return 0;
    return Math.max(...sortedProjectCounts.map(([, count]) => count));
  });
</script>

{#if cleanupStats || cleanupStatsLoading}
  <div class="bg-card rounded-lg border border-border shadow-card p-4">
    <div class="flex items-center gap-2 mb-3">
      <h3 class="text-sm font-semibold text-foreground">Nightly Cleanup 통계</h3>
      <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">최근 14일</span>
      {#if cleanupStats}
        <span class="ml-auto text-[10px] text-muted-foreground">
          총 {cleanupStats.summary.total_runs}회 실행 · {cleanupStats.summary.total_items_archived.toLocaleString()}개 아카이브 · 평균 {cleanupStats.summary.avg_items_per_run}/회
        </span>
      {/if}
    </div>

    {#if cleanupStatsLoading}
      <p class="text-sm text-muted-foreground py-4 text-center">통계 로딩 중...</p>
    {:else if cleanupStats}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">일별 실행 이력</div>
          <div class="overflow-x-auto">
            <table class="w-full text-[11px]">
              <thead>
                <tr class="border-b border-border">
                  <th class="text-left px-2 py-1 text-muted-foreground font-medium">날짜</th>
                  <th class="text-right px-2 py-1 text-muted-foreground font-medium">항목수</th>
                  <th class="text-right px-2 py-1 text-muted-foreground font-medium">프로젝트</th>
                  <th class="text-right px-2 py-1 text-muted-foreground font-medium">소요</th>
                  <th class="text-center px-2 py-1 text-muted-foreground font-medium">상태</th>
                </tr>
              </thead>
              <tbody>
                {#each cleanupStats.runs as run}
                  <tr class="border-b border-border/50 hover:bg-muted/50">
                    <td class="px-2 py-1.5 font-mono text-foreground">{run.date}</td>
                    <td class="px-2 py-1.5 text-right font-semibold {run.total_items > 0 ? 'text-primary' : 'text-muted-foreground'}">{run.total_items.toLocaleString()}</td>
                    <td class="px-2 py-1.5 text-right text-muted-foreground">{run.processed}</td>
                    <td class="px-2 py-1.5 text-right font-mono text-muted-foreground">{run.duration ?? '-'}</td>
                    <td class="px-2 py-1.5 text-center">
                      {#if run.failed > 0}
                        <span class="text-[10px] px-1.5 py-0.5 rounded bg-error-light text-error">실패 {run.failed}</span>
                      {:else}
                        <span class="text-[10px] px-1.5 py-0.5 rounded bg-success-light text-success">성공</span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">프로젝트별 누적 (14일)</div>
          {#each sortedProjectCounts as [proj, count]}
            <div class="flex items-center gap-2 py-1">
              <span class="text-[11px] text-foreground w-36 truncate shrink-0" title={proj}>{proj}</span>
              <div class="flex-1 bg-muted rounded-full h-1.5 overflow-hidden">
                <div class="h-full bg-primary rounded-full" style="width: {maxProjectCount > 0 ? Math.round((count / maxProjectCount) * 100) : 0}%"></div>
              </div>
              <span class="text-[11px] font-mono text-muted-foreground w-12 text-right shrink-0">{count.toLocaleString()}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  </div>
{/if}
