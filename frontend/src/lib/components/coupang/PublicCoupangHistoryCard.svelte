<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';
  import { formatDuration, formatKoreanDateTime } from '$lib/utils/coupangHistoryDisplay';

  interface Props {
    items: CoupangPublicHistoryItem[];
  }

  let { items }: Props = $props();

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

<div class="md:hidden space-y-2">
  {#each items as item (item.id)}
    <article class="rounded-lg border border-border bg-card p-3 shadow-sm">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-foreground">{item.option_label}</p>
          <p class="mt-1 text-xs text-muted-foreground">발견 {formatKoreanDateTime(item.timestamp, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</p>
        </div>

        <span class={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${statusTone(item.status_label)}`}>
          {item.status_label}
        </span>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">날짜</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{item.schedule_date ?? '-'}</div>
        </div>
        <div class="rounded-md bg-muted/40 px-2 py-1.5">
          <div class="text-[11px] text-muted-foreground">소요시간</div>
          <div class="mt-0.5 text-sm font-medium text-foreground">{durationLabel(item)}</div>
        </div>
      </div>
    </article>
  {/each}
</div>
