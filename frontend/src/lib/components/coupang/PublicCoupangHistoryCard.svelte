<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';
  import { formatDurationList } from '$lib/utils/coupangHistoryDisplay';

  interface Props {
    items: CoupangPublicHistoryItem[];
  }

  let { items }: Props = $props();

  function formatDatetime(ts: string): string {
    const date = new Date(ts);
    return date.toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function transitionTone(lastTransitionLabel: string): string {
    switch (lastTransitionLabel) {
      case '취소표발생':
        return 'bg-emerald-100 text-emerald-700';
      case '다시 매진':
        return 'bg-rose-100 text-rose-700';
      case '판매 관측':
        return 'bg-sky-100 text-sky-700';
      case '잔여석발생':
        return 'bg-violet-100 text-violet-700';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  function transitionTitle(lastTransitionLabel: string): string {
    return lastTransitionLabel || '-';
  }
</script>

<div class="md:hidden space-y-2">
  {#each items as item (item.id)}
    <article class="rounded-lg border border-border bg-card p-3 shadow-sm">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-foreground">{item.option_label}</p>
          <p class="mt-1 text-xs text-muted-foreground">
            감지시각 {formatDatetime(item.timestamp)}
            {#if item.slot_time_label}
              · {item.slot_time_label}
            {/if}
          </p>
        </div>

        <span class={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${transitionTone(item.last_transition_label)}`}>
          {transitionTitle(item.last_transition_label)}
        </span>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">날짜</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{item.schedule_date ?? '-'}</div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">상태</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{transitionTitle(item.last_transition_label)}</div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">수량</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">
            취소 {item.cancellation_count} · 판매 {item.sold_count} · 잔여 {item.remaining_open_count}
          </div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">소요시간</div>
          <div class="mt-0.5 space-y-1 text-[11px] font-medium text-foreground">
            <div>판매 {formatDurationList(item.sale_durations)}</div>
            <div>잔여 {formatDurationList(item.open_durations)}</div>
          </div>
        </div>
      </div>
    </article>
  {/each}
</div>
