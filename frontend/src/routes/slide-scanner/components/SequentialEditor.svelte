<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  import type { SlideDetailResponse, SlidePoint } from '$lib/api/slide-scanner';

  import CornerEditor from './CornerEditor.svelte';
  import KeyboardShortcuts from './KeyboardShortcuts.svelte';

  const dispatch = createEventDispatcher<{
    changePoints: { points: SlidePoint[] };
    prev: void;
    next: void;
    review: void;
    transform: void;
    saveAll: void;
  }>();

  export let slide: SlideDetailResponse | null = null;
  export let points: SlidePoint[] = [];
  export let imageUrl = '';
  export let canPrev = false;
  export let canNext = false;
  export let reviewing = false;
  export let transforming = false;
  export let inheritedApplied = false;
  export let aspectRatioLabel = 'Auto';

  function handlePointsChange(event: CustomEvent<{ points: SlidePoint[] }>) {
    dispatch('changePoints', { points: event.detail.points });
  }
</script>

{#if slide}
  <section class="space-y-3 rounded-xl border border-border bg-card p-4">
    <KeyboardShortcuts
      enabled={Boolean(slide)}
      disabled={reviewing || transforming}
      {canPrev}
      {canNext}
      on:prev={() => dispatch('prev')}
      on:next={() => dispatch('next')}
      on:confirm={() => dispatch('transform')}
      on:saveAll={() => dispatch('saveAll')}
    />

    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 class="text-sm font-semibold">{slide.file_name}</h2>
        <p class="text-xs text-muted-foreground">
          {inheritedApplied ? '이전 확정 좌표를 초기값으로 적용했습니다.' : '자동 검출 좌표를 초기값으로 사용합니다.'}
        </p>
        <p class="text-[11px] text-muted-foreground">선택 비율: {aspectRatioLabel}</p>
      </div>
      <div class="flex items-center gap-2">
        <button type="button" class="btn btn-outline btn-sm" onclick={() => dispatch('prev')} disabled={!canPrev}>
          이전
        </button>
        <button type="button" class="btn btn-outline btn-sm" onclick={() => dispatch('next')} disabled={!canNext}>
          다음
        </button>
      </div>
    </div>

    <CornerEditor {imageUrl} {points} on:change={handlePointsChange} />

    <div class="flex flex-wrap items-center justify-end gap-2">
      <button
        type="button"
        class="btn btn-outline"
        onclick={() => dispatch('review')}
        disabled={reviewing || points.length !== 4}
      >
        {reviewing ? '확정 중...' : '확정 (REVIEWED)'}
      </button>
      <button
        type="button"
        class="btn btn-primary"
        onclick={() => dispatch('transform')}
        disabled={transforming || points.length !== 4}
      >
        {transforming ? '변환 중...' : '보정 실행'}
      </button>
    </div>

    <p class="text-[11px] text-muted-foreground">
      단축키: `Space` 다음, `Enter` 보정 실행, `Ctrl+S` 전체 저장, `←/→` 이동
    </p>
  </section>
{:else}
  <section class="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
    갤러리에서 이미지를 선택하면 연속 작업 에디터가 열립니다.
  </section>
{/if}
