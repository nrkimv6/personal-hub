<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';
  import { formatDuration, formatKoreanDateTime } from '$lib/utils/coupangHistoryDisplay';

  interface Props {
    items: CoupangPublicHistoryItem[];
  }

  let { items }: Props = $props();

  function closedStatusTone(): string {
    return 'bg-rose-100 text-rose-700';
  }

  function openStatusTone(): string {
    return 'bg-sky-100 text-sky-700';
  }

  function durationLabel(item: CoupangPublicHistoryItem): string {
    if (item.status_label === '다시 매진') {
      return formatDuration(item.closed_duration_seconds);
    }
    return formatDuration(item.open_duration_seconds);
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
          <td class="whitespace-nowrap text-sm text-muted-foreground">{formatKoreanDateTime(item.timestamp, { year: '2-digit', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</td>
          <td>
            {#if item.status_label === '다시 매진'}
              <div class="flex flex-wrap gap-1">
                <span class={`badge badge-sm shrink-0 ${closedStatusTone()}`}>빈자리</span>
                <span class={`badge badge-sm shrink-0 ${closedStatusTone()}`}>매진</span>
              </div>
            {:else}
              <span class={`badge badge-sm shrink-0 ${openStatusTone()}`}>열림</span>
            {/if}
          </td>
          <td>
            <div class="text-sm font-medium text-foreground">{item.option_label}</div>
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
