<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';
  import { formatDuration } from '$lib/utils/coupangHistoryDisplay';

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

  function statusTone(statusLabel: string): string {
    switch (statusLabel) {
      case '다시 매진':
        return 'bg-rose-100 text-rose-700';
      case '현재 열림':
        return 'bg-sky-100 text-sky-700';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  function durationLabel(item: CoupangPublicHistoryItem): string {
    if (item.status_label === '다시 매진') {
      return `다시 매진까지 ${formatDuration(item.closed_duration_seconds)}`;
    }
    return `현재 열림 ${formatDuration(item.open_duration_seconds)}`;
  }
</script>

<div class="hidden md:block overflow-x-auto">
  <table class="table w-full">
    <thead>
      <tr>
        <th>발견 시각</th>
        <th>상태</th>
        <th>옵션</th>
        <th>날짜</th>
        <th class="text-center">소요시간</th>
      </tr>
    </thead>
    <tbody>
      {#each items as item (item.id)}
        <tr>
          <td class="whitespace-nowrap text-sm text-muted-foreground">{formatDatetime(item.timestamp)}</td>
          <td>
            <span class={`badge badge-sm shrink-0 ${statusTone(item.status_label)}`}>
              {item.status_label}
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
            {durationLabel(item)}
          </td>
        </tr>
      {:else}
        <tr>
          <td colspan="5" class="py-8 text-center text-sm text-muted-foreground">
            조건에 맞는 공개 이력이 없습니다.
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
