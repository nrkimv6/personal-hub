<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
  import type { SlideListItem } from '$lib/api/slide-scanner';

  const dispatch = createEventDispatcher<{
    toggle: { id: number };
    open: { id: number };
  }>();

  export let slide: SlideListItem;
  export let selected = false;

  function toggleSelection() {
    dispatch('toggle', { id: slide.id });
  }

  function openDetail() {
    dispatch('open', { id: slide.id });
  }

  function statusVariant(status: SlideListItem['status']) {
    if (status === 'DONE') return 'success';
    if (status === 'REVIEWED') return 'info';
    return 'gray';
  }

  function statusLabel(status: SlideListItem['status']) {
    if (status === 'DONE') return '완료';
    if (status === 'REVIEWED') return '검토됨';
    return '대기';
  }

  function formatCapturedAt(value?: string | null) {
    if (!value) return '시간 미상';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }
</script>

<article
  class="group rounded-lg border border-border bg-card p-2 transition-colors hover:border-primary/40"
  onclick={openDetail}
>
  <div class="relative mb-2 overflow-hidden rounded-md bg-muted">
    <img
      src={`/api/v1/ss/slides/${slide.id}/thumbnail`}
      alt={slide.file_name}
      loading="lazy"
      class="aspect-square h-auto w-full object-cover"
    />
    <label class="absolute right-2 top-2 rounded bg-background/80 px-1.5 py-1" onclick={(event) => event.stopPropagation()}>
      <input type="checkbox" checked={selected} onclick={toggleSelection} />
    </label>
  </div>

  <div class="space-y-1">
    <p class="line-clamp-1 text-xs font-medium text-foreground">{slide.file_name}</p>
    <p class="text-[11px] text-muted-foreground">{formatCapturedAt(slide.captured_at)}</p>
    {#if slide.tag}
      <p class="line-clamp-1 text-[11px] text-primary">#{slide.tag}</p>
    {/if}
    <div class="flex items-center justify-between pt-1">
      <StatusBadge variant={statusVariant(slide.status)} size="sm">{statusLabel(slide.status)}</StatusBadge>
      <span class="text-[11px] text-muted-foreground">#{slide.id}</span>
    </div>
  </div>
</article>
