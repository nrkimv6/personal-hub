<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';
  import { formatDurationList } from '$lib/utils/coupangHistoryDisplay';

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

<div class="hidden md:block overflow-x-auto">
  <table class="table w-full">
    <thead>
      <tr>
        <th>발견시간</th>
        <th>상태</th>
        <th>옵션</th>
        <th>날짜</th>
        <th class="text-center">다시 매진까지</th>
        <th class="text-center">현재 열림 유지</th>
      </tr>
    </thead>
    <tbody>
      {#each items as item (item.slot_key)}
        <tr>
          <td class="whitespace-nowrap text-sm text-muted-foreground">{formatDatetime(item.timestamp)}</td>
          <td>
            <span class={`badge badge-sm shrink-0 ${transitionTone(item.last_transition_label)}`}>
              {transitionTitle(item.last_transition_label)}
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
          <td class="text-center text-sm text-muted-foreground">
            {formatDurationList(item.sale_durations)}
          </td>
          <td class="text-center text-sm text-muted-foreground">
            {formatDurationList(item.open_durations)}
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
