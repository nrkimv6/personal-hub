<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  import type { SlideFilterOptions } from '$lib/api/slide-scanner';

  const dispatch = createEventDispatcher<{
    change: { value: SlideFilterOptions };
  }>();

  export let value: SlideFilterOptions = {
    white_balance: false,
    contrast: 1.0,
    document_mode: false
  };
  export let disabled = false;

  function emit(next: SlideFilterOptions) {
    if (disabled) return;
    dispatch('change', { value: next });
  }

  function toggleWhiteBalance() {
    emit({ ...value, white_balance: !value.white_balance });
  }

  function toggleDocumentMode() {
    emit({ ...value, document_mode: !value.document_mode });
  }

  function handleContrastInput(event: Event) {
    const target = event.currentTarget as HTMLInputElement | null;
    if (!target) return;
    emit({
      ...value,
      contrast: Number.parseFloat(target.value)
    });
  }

  function resetFilters() {
    emit({
      white_balance: false,
      contrast: 1.0,
      document_mode: false
    });
  }

  $: hasActiveFilter =
    value.white_balance || value.document_mode || Math.abs(value.contrast - 1.0) >= 1e-6;
  $: contrastLabel = value.contrast.toFixed(1);
</script>

<section class="rounded-xl border border-border bg-card p-3">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div>
      <h3 class="text-xs font-semibold text-foreground">이미지 필터</h3>
      <p class="text-[11px] text-muted-foreground">화이트 밸런스/대비/문서 모드를 조합해 보정 결과를 조절합니다.</p>
    </div>
    <button type="button" class="btn btn-ghost btn-xs" onclick={resetFilters} disabled={disabled || !hasActiveFilter}>
      초기화
    </button>
  </div>

  <div class="mt-3 flex flex-wrap items-center gap-2">
    <button
      type="button"
      class="btn btn-xs {value.white_balance ? 'btn-primary' : 'btn-outline'}"
      onclick={toggleWhiteBalance}
      disabled={disabled}
    >
      화이트 밸런스
    </button>
    <button
      type="button"
      class="btn btn-xs {value.document_mode ? 'btn-primary' : 'btn-outline'}"
      onclick={toggleDocumentMode}
      disabled={disabled}
    >
      문서 모드
    </button>
  </div>

  <div class="mt-3 space-y-1">
    <div class="flex items-center justify-between text-xs">
      <span class="font-medium text-muted-foreground">대비</span>
      <span class="font-mono text-foreground">{contrastLabel}</span>
    </div>
    <input
      type="range"
      min="0.5"
      max="2.0"
      step="0.1"
      value={value.contrast}
      oninput={handleContrastInput}
      disabled={disabled}
      class="w-full accent-primary"
    />
  </div>
</section>
