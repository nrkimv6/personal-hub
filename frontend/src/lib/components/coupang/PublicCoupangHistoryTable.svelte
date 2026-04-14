<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';

  interface Props {
    items: CoupangPublicHistoryItem[];
  }

  let { items }: Props = $props();

  function formatDatetime(ts: string): string {
    const d = new Date(ts);
    return d.toLocaleString('ko-KR', {
      year: '2-digit',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
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

<div class="hidden md:block overflow-x-auto">
  <table class="table w-full">
    <thead>
      <tr>
        <th>감지 시각</th>
        <th>전환</th>
        <th>옵션</th>
        <th>날짜</th>
        <th class="text-center">수량</th>
        <th class="text-center">소요시간</th>
      </tr>
    </thead>
    <tbody>
      {#each items as item (item.id)}
        <tr>
          <td class="whitespace-nowrap text-sm text-muted-foreground">{formatDatetime(item.timestamp)}</td>
          <td>
            <span class={`badge badge-sm shrink-0 ${transitionTone(item.transition_type)}`}>
              {transitionTitle(item.transition_type)}
            </span>
          </td>
          <td>
            <div class="space-y-1">
              <div class="text-sm font-medium text-foreground">{item.option_label}</div>
              <div class="text-xs text-muted-foreground">
                {#if item.slot_time_label}
                  {item.slot_time_label}
                {:else}
                  -
                {/if}
              </div>
            </div>
          </td>
          <td class="text-sm">{item.schedule_date ?? '-'}</td>
          <td class="text-center">
            {#if item.delta_count > 1}
              <span class="badge badge-secondary">x{item.delta_count}</span>
            {:else if item.delta_count === 1}
              <span class="text-sm text-muted-foreground">1</span>
            {:else}
              <span class="text-sm text-muted-foreground">-</span>
            {/if}
          </td>
          <td class="text-center text-sm text-muted-foreground">
            {item.observed_sale_seconds != null
              ? formatDuration(item.observed_sale_seconds)
              : item.observed_open_seconds != null
                ? formatDuration(item.observed_open_seconds)
                : '-'}
          </td>
        </tr>
      {:else}
        <tr>
          <td colspan="6" class="py-8 text-center text-sm text-muted-foreground">
            조건에 맞는 공개 전환 이력이 없습니다.
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
