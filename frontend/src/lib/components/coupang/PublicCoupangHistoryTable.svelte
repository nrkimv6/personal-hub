<script lang="ts">
  import type { MonitoringEvent } from '$lib/types';
  import { getCoupangHistoryDisplay, getCoupangHistoryTimeLabel } from '$lib/utils/coupangHistoryDisplay';

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
</script>

<div class="hidden md:block overflow-x-auto">
  <table class="table w-full">
    <thead>
      <tr>
        <th>감지 시각</th>
        <th>옵션 정보</th>
        <th>날짜</th>
        <th class="text-center">가용석</th>
      </tr>
    </thead>
    <tbody>
      {#each events as ev (ev.id)}
        {@const display = getCoupangHistoryDisplay(ev)}
        <tr>
          <td class="whitespace-nowrap text-sm text-muted-foreground">{formatDatetime(ev.timestamp)}</td>
          <td>
            <div class="space-y-1">
              <div class="flex items-center gap-2">
                <span class="min-w-0 truncate text-sm font-medium text-foreground">
                  {display.primaryLabel}
                  {#if display.extraOptionCount > 0}
                    <span class="font-normal text-muted-foreground"> +{display.extraOptionCount}개</span>
                  {/if}
                </span>
                <span class="badge badge-warning badge-sm shrink-0">취소 감지</span>
              </div>
              <div class="text-xs text-muted-foreground">시간 {getCoupangHistoryTimeLabel(ev, display)}</div>
            </div>
          </td>
          <td class="text-sm">{ev.schedule_date ?? '-'}</td>
          <td class="text-center">
            {#if ev.available_count > 0}
              <span class="badge badge-success">{ev.available_count}석</span>
            {:else}
              <span class="text-xs text-muted-foreground">-</span>
            {/if}
          </td>
        </tr>
      {:else}
        <tr>
          <td colspan="4" class="py-8 text-center text-sm text-muted-foreground">
            조건에 맞는 취소이력이 없습니다.
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
