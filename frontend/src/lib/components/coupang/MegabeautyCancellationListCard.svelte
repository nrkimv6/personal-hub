<script lang="ts">
  import type { MonitoringEvent } from '$lib/types';

  interface Props {
    events: MonitoringEvent[];
  }

  let { events }: Props = $props();

  function formatDatetime(ts: string): string {
    const d = new Date(ts);
    return (
      d.toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' }) +
      ' ' +
      d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
    );
  }

  function getDisplayItemName(name: string | null | undefined): string {
    const cleaned = (name ?? '')
      .replace(/2026\s*쿠팡\s*메가뷰티쇼/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    return cleaned || '메가뷰티쇼';
  }
</script>

<div class="md:hidden space-y-2">
  {#each events as ev (ev.id)}
    <div class="rounded-lg border border-border bg-card p-3">
      <div class="flex items-start justify-between gap-2 mb-1">
        <div class="flex-1 min-w-0">
          <p class="font-medium text-sm truncate">{getDisplayItemName(ev.biz_item_name)}</p>
          <p class="text-xs text-muted-foreground truncate">메가뷰티쇼 취소이력</p>
        </div>
        <span class="shrink-0 rounded-full bg-orange-100 text-orange-700 text-xs px-2 py-0.5 font-medium">
          메가뷰티쇼 감지
        </span>
      </div>
      <div class="flex items-center gap-3 text-xs text-muted-foreground mt-1">
        <span>{formatDatetime(ev.timestamp)}</span>
        {#if ev.schedule_date}
          <span class="text-foreground font-medium">여행일 {ev.schedule_date}</span>
        {/if}
        {#if ev.available_count > 0}
          <span class="text-success font-medium">{ev.available_count}석</span>
        {/if}
      </div>
    </div>
  {/each}
</div>
