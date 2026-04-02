<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher<{
    toggleAll: void;
    transform: void;
    archive: void;
    exportPdf: void;
  }>();

  export let selectedCount = 0;
  export let allSelected = false;
  export let transforming = false;
  export let archiving = false;
  export let exportingPdf = false;
  export let disabled = false;
</script>

<div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 p-2">
  <p class="text-xs text-muted-foreground">선택 {selectedCount}건</p>
  <div class="flex items-center gap-2">
    <button type="button" class="btn btn-outline btn-sm" onclick={() => dispatch('toggleAll')} disabled={disabled}>
      {allSelected ? '전체 해제' : '전체 선택'}
    </button>
    <button
      type="button"
      class="btn btn-outline btn-sm"
      onclick={() => dispatch('transform')}
      disabled={disabled || selectedCount === 0 || transforming}
    >
      {transforming ? '변환 중...' : '일괄 변환'}
    </button>
    <button
      type="button"
      class="btn btn-outline btn-sm"
      onclick={() => dispatch('archive')}
      disabled={disabled || selectedCount === 0 || archiving}
    >
      {archiving ? '아카이브 중...' : '아카이브'}
    </button>
    <button
      type="button"
      class="btn btn-outline btn-sm"
      onclick={() => dispatch('exportPdf')}
      disabled={disabled || selectedCount === 0 || exportingPdf}
    >
      {exportingPdf ? 'PDF 생성 중...' : 'PDF로 내보내기'}
    </button>
  </div>
</div>
