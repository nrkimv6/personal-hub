<script lang="ts">
  import type { CoupangPublicHistoryItem } from '$lib/types';
  import { formatDuration, formatKoreanDateTime } from '$lib/utils/coupangHistoryDisplay';

  interface Props {
    items: CoupangPublicHistoryItem[];
  }

  let { items }: Props = $props();

  function availableStatusTone(): string {
    return 'bg-emerald-100 text-emerald-700';
  }

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

  function detailParts(item: CoupangPublicHistoryItem): string[] {
    const parts: string[] = [];

    const duration = durationLabel(item);
    if (duration !== '-') {
      parts.push(`유지 ${duration}`);
    }

    return parts;
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

        {#if item.status_label === '다시 매진'}
          <div class="flex shrink-0 items-center gap-1">
            <span class={`rounded-full px-2 py-0.5 text-xs font-medium ${availableStatusTone()}`}>빈자리</span>
            <span class={`rounded-full px-2 py-0.5 text-xs font-medium ${closedStatusTone()}`}>매진</span>
          </div>
        {:else}
          <span class={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${openStatusTone()}`}>열림</span>
        {/if}
      </div>

      {#if detailParts(item).length > 0}
        <p class="mt-3 text-xs text-muted-foreground">{detailParts(item).join(' · ')}</p>
      {/if}
    </article>
  {/each}
</div>
