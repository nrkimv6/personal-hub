<script lang="ts">
  import type { MonitoringEvent } from '$lib/types';

  interface Props {
    events: MonitoringEvent[];
  }

  let { events }: Props = $props();

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

  function getDisplayItemName(name: string | null | undefined): string {
    const cleaned = (name ?? '')
      .replace(/2026\s*쿠팡\s*메가뷰티쇼/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    return cleaned || '메가뷰티쇼';
  }
</script>

<div class="hidden md:block overflow-x-auto">
  <table class="table w-full">
    <thead>
      <tr>
        <th>감지 시각</th>
        <th>상품명</th>
        <th>여행일</th>
        <th class="text-center">가용석</th>
      </tr>
    </thead>
    <tbody>
      {#each events as ev (ev.id)}
        <tr>
          <td class="text-sm text-muted-foreground whitespace-nowrap">{formatDatetime(ev.timestamp)}</td>
          <td class="font-medium text-sm">{getDisplayItemName(ev.biz_item_name)}</td>
          <td class="text-sm">{ev.schedule_date ?? '-'}</td>
          <td class="text-center">
            {#if ev.available_count > 0}
              <span class="badge badge-success">{ev.available_count}석</span>
            {:else}
              <span class="text-muted-foreground text-xs">-</span>
            {/if}
          </td>
        </tr>
      {:else}
        <tr>
          <td colspan="4" class="text-center text-sm text-muted-foreground py-8">
            메가뷰티쇼 취소이력이 없습니다.
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
