<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';

  import { slideScannerApi, type SlideListItem, type SlideStatus } from '$lib/api/slide-scanner';
  import { createOffsetPagination } from '$lib/utils/pagination.svelte';
  import { createSelection } from '$lib/utils/selection.svelte';

  import ScanFolderModal from './ScanFolderModal.svelte';
  import SlideCard from './SlideCard.svelte';

  type StatusFilter = 'ALL' | SlideStatus;
  const dispatch = createEventDispatcher<{
    open: { slideId: number; sequenceIds: number[] };
  }>();

  const pager = createOffsetPagination(24);
  const selection = createSelection();

  const statusFilters: StatusFilter[] = ['ALL', 'PENDING', 'REVIEWED', 'DONE'];
  const filterLabel: Record<StatusFilter, string> = {
    ALL: '전체',
    PENDING: '대기',
    REVIEWED: '검토됨',
    DONE: '완료'
  };

  let mounted = false;
  let slides = $state<SlideListItem[]>([]);
  let statusFilter = $state<StatusFilter>('ALL');
  let loading = $state(false);
  let loadingMore = $state(false);
  let scanning = $state(false);
  let errorMessage = $state('');
  let scanMessage = $state('');
  let showScanModal = $state(false);

  let allCurrentIds = $derived(slides.map((slide) => slide.id));
  let allSelected = $derived(
    allCurrentIds.length > 0 ? selection.isAllSelected(allCurrentIds) : false
  );

  function parseError(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  async function loadSlides(reset = false) {
    if (reset) {
      loading = true;
      errorMessage = '';
      pager.reset();
      slides = [];
      selection.clear();
    } else {
      loadingMore = true;
      errorMessage = '';
    }

    try {
      const result = await slideScannerApi.getSlideList({
        skip: pager.offset,
        limit: pager.limit,
        status: statusFilter
      });

      if (reset) {
        slides = result.slides;
      } else {
        slides = [...slides, ...result.slides];
      }
      pager.advance(result.slides.length, result.total);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      loading = false;
      loadingMore = false;
    }
  }

  async function handleScanSubmit(event: CustomEvent<{ folderPath: string; recursive: boolean }>) {
    scanning = true;
    errorMessage = '';
    scanMessage = '';

    try {
      const result = await slideScannerApi.scanFolder(event.detail.folderPath, {
        recursive: event.detail.recursive
      });
      scanMessage =
        `스캔 완료: 등록 ${result.created}건, 중복 ${result.skipped}건, 실패 ${result.failed}건`;
      showScanModal = false;
      await loadSlides(true);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      scanning = false;
    }
  }

  function toggleSelection(event: CustomEvent<{ id: number }>) {
    selection.toggle(event.detail.id);
  }

  function openInEditor(event: CustomEvent<{ id: number }>) {
    dispatch('open', { slideId: event.detail.id, sequenceIds: [...allCurrentIds] });
  }

  onMount(() => {
    mounted = true;
    void loadSlides(true);
  });

  $effect(() => {
    void statusFilter;
    if (!mounted) return;
    void loadSlides(true);
  });
</script>

<section class="space-y-3 rounded-xl border border-border bg-card p-4">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div>
      <h2 class="text-sm font-semibold">갤러리</h2>
      <p class="text-xs text-muted-foreground">
        총 {pager.total}건, 선택 {selection.count}건
      </p>
    </div>
    <div class="flex items-center gap-2">
      <button type="button" class="btn btn-outline btn-sm" onclick={() => selection.selectAll(allCurrentIds)} disabled={slides.length === 0}>
        {allSelected ? '전체 해제' : '전체 선택'}
      </button>
      <button type="button" class="btn btn-primary btn-sm" onclick={() => (showScanModal = true)}>
        폴더 스캔
      </button>
    </div>
  </div>

  <div class="flex flex-wrap gap-2">
    {#each statusFilters as filter}
      <button
        type="button"
        class="btn btn-sm {statusFilter === filter ? 'btn-primary' : 'btn-outline'}"
        onclick={() => (statusFilter = filter)}
      >
        {filterLabel[filter]}
      </button>
    {/each}
  </div>

  {#if scanMessage}
    <p class="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
      {scanMessage}
    </p>
  {/if}

  {#if errorMessage}
    <p class="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">{errorMessage}</p>
  {/if}

  {#if loading}
    <p class="text-sm text-muted-foreground">갤러리 로딩 중...</p>
  {:else if slides.length === 0}
    <p class="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
      등록된 이미지가 없습니다. 폴더 스캔으로 이미지를 추가해 주세요.
    </p>
  {:else}
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
      {#each slides as slide (slide.id)}
        <SlideCard
          {slide}
          selected={selection.has(slide.id)}
          on:toggle={toggleSelection}
          on:open={openInEditor}
        />
      {/each}
    </div>

    {#if pager.hasMore}
      <div class="pt-2 text-center">
        <button type="button" class="btn btn-outline btn-sm" onclick={() => void loadSlides(false)} disabled={loadingMore}>
          {loadingMore ? '불러오는 중...' : '더 보기'}
        </button>
      </div>
    {/if}
  {/if}
</section>

<ScanFolderModal
  open={showScanModal}
  busy={scanning}
  on:close={() => (showScanModal = false)}
  on:submit={handleScanSubmit}
/>
