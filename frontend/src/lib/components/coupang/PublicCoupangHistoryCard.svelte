<script lang="ts">
  import type { MonitoringEvent } from '$lib/types';
  import { getCoupangHistoryDisplay, getCoupangHistoryTimeLabel } from '$lib/utils/coupangHistoryDisplay';

  interface Props {
    events: MonitoringEvent[];
  }

  let { events }: Props = $props();

  function formatDatetime(ts: string): string {
    return new Date(ts).toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }
</script>

<div class="md:hidden space-y-2">
  {#each events as ev (ev.id)}
    {@const display = getCoupangHistoryDisplay(ev)}
    <article class="rounded-lg border border-border bg-card p-3 shadow-sm">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-foreground">
            {display.primaryLabel}
            {#if display.extraOptionCount > 0}
              <span class="font-normal text-muted-foreground"> +{display.extraOptionCount}개</span>
            {/if}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">감지시각 {formatDatetime(ev.timestamp)}</p>
        </div>

        <span class="shrink-0 rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
          취소 감지
        </span>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">날짜</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{ev.schedule_date ?? '-'}</div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">시간</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{getCoupangHistoryTimeLabel(ev, display)}</div>
        </div>
        <div class="col-span-2 rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">가용석</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">
            {ev.available_count > 0 ? `${ev.available_count}석` : '-'}
          </div>
        </div>
      </div>
    </article>
  {/each}
</div>
