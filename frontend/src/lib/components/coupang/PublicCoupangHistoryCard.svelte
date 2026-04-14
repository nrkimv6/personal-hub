<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';

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

  function formatDuration(seconds: number | null | undefined): string {
    if (seconds == null || Number.isNaN(seconds)) return '-';
    const rounded = Math.max(0, Math.round(seconds));
    if (rounded < 60) return `약 ${rounded}초`;
    const minutes = Math.floor(rounded / 60);
    const rest = rounded % 60;
    return rest > 0 ? `약 ${minutes}분 ${rest}초` : `약 ${minutes}분`;
  }

  function transitionTone(transitionType: string): string {
    switch (transitionType) {
      case 'cancellation':
        return 'bg-emerald-100 text-emerald-700';
      case 'sold_out':
        return 'bg-rose-100 text-rose-700';
      case 'sale_observed':
        return 'bg-sky-100 text-sky-700';
      case 'bulk_sale':
        return 'bg-amber-100 text-amber-700';
      case 'open':
        return 'bg-violet-100 text-violet-700';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  function transitionTitle(transitionType: string): string {
    switch (transitionType) {
      case 'cancellation':
        return '취소표발생';
      case 'sold_out':
        return '다시 매진';
      case 'sale_observed':
        return '판매 관측';
      case 'bulk_sale':
        return '재고 감소';
      case 'open':
        return '잔여석발생';
      default:
        return transitionType;
    }
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

        <span class={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${transitionTone(item.transition_type)}`}>
          {transitionTitle(item.transition_type)}
        </span>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">날짜</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{item.schedule_date ?? '-'}</div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">전환</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{transitionTitle(item.transition_type)}</div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">수량</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">
            {item.delta_count > 0 ? `x${item.delta_count}` : '-'}
          </div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">소요시간</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">
            {item.observed_sale_seconds != null
              ? formatDuration(item.observed_sale_seconds)
              : item.observed_open_seconds != null
                ? formatDuration(item.observed_open_seconds)
                : '-'}
          </div>
        </div>
      </div>
    </article>
  {/each}
</div>
