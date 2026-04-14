<script lang="ts">
  import { onMount } from 'svelte';

  import { slideScannerApi, type SlideListItem, type SlideStatus } from '$lib/api/slide-scanner';
  import { createOffsetPagination } from '$lib/utils/pagination.svelte';
  import { createSelection } from '$lib/utils/selection.svelte';

  import BatchActionBar from './BatchActionBar.svelte';
  import PdfExportModal from './PdfExportModal.svelte';
  import ScanFolderModal from './ScanFolderModal.svelte';
  import SlideCard from './SlideCard.svelte';

  type StatusFilter = 'ALL' | SlideStatus;
  const { onopen }: { onopen?: (detail: { slideId: number; sequenceIds: number[] }) => void } = $props();

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
  let batchTransforming = $state(false);
  let archiving = $state(false);
  let exportingPdf = $state(false);
  let errorMessage = $state('');
  let noticeMessage = $state('');
  let showScanModal = $state(false);
  let showPdfModal = $state(false);
  let searchInput = $state('');
  let searchQuery = $state('');
  let tagFilter = $state('ALL');
  let availableTags = $state<string[]>([]);

  let allCurrentIds = $derived(slides.map((slide) => slide.id));
  let allSelected = $derived(
    allCurrentIds.length > 0 ? selection.isAllSelected(allCurrentIds) : false
  );
  let selectedSlides = $derived.by(() =>
    slides
      .filter((slide) => selection.has(slide.id))
      .sort((a, b) => {
        const aMissing = !a.captured_at;
        const bMissing = !b.captured_at;
        if (aMissing !== bMissing) return aMissing ? 1 : -1;
        if ((a.captured_at ?? '') !== (b.captured_at ?? '')) {
          return (a.captured_at ?? '').localeCompare(b.captured_at ?? '');
        }
        return a.id - b.id;
      })
      .map((slide) => ({
        id: slide.id,
        file_name: slide.file_name,
        captured_at: slide.captured_at
      }))
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
      if (reset) {
        await loadTags();
      }
      const result = await slideScannerApi.getSlideList({
        skip: pager.offset,
        limit: pager.limit,
        status: statusFilter,
        search: searchQuery || undefined,
        tag: tagFilter !== 'ALL' ? tagFilter : undefined
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

  async function loadTags() {
    try {
      const result = await slideScannerApi.getTags();
      availableTags = result.tags;
      if (tagFilter !== 'ALL' && !result.tags.includes(tagFilter)) {
        tagFilter = 'ALL';
      }
    } catch {
      availableTags = [];
    }
  }

  async function handleScanSubmit(detail: { folderPath: string; recursive: boolean }) {
    scanning = true;
    errorMessage = '';
    noticeMessage = '';

    try {
      const result = await slideScannerApi.scanFolder(detail.folderPath, {
        recursive: detail.recursive
      });
      noticeMessage =
        `스캔 완료: 등록 ${result.created}건, 중복 ${result.skipped}건, 실패 ${result.failed}건`;
      showScanModal = false;
      await loadSlides(true);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      scanning = false;
    }
  }

  async function handleBatchTransform() {
    const ids = selection.toArray();
    if (ids.length === 0) return;

    batchTransforming = true;
    errorMessage = '';
    noticeMessage = '';
    try {
      const result = await slideScannerApi.batchTransform(ids);
      noticeMessage =
        `일괄 변환 완료: 성공 ${result.done}건, 스킵 ${result.skipped}건, 실패 ${result.failed}건`;
      selection.clear();
      await loadSlides(true);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      batchTransforming = false;
    }
  }

  async function handleArchive() {
    const ids = selection.toArray();
    if (ids.length === 0) return;

    archiving = true;
    errorMessage = '';
    noticeMessage = '';
    try {
      const result = await slideScannerApi.archiveSlides(ids);
      noticeMessage =
        `아카이브 완료: 압축 ${result.archived}건, 스킵 ${result.skipped.length}건`;
      selection.clear();
      await loadSlides(true);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      archiving = false;
    }
  }

  function downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  async function handlePdfSubmit(detail: { filename: string }) {
    const ids = selectedSlides.map((slide) => slide.id);
    if (ids.length === 0) return;

    exportingPdf = true;
    errorMessage = '';
    noticeMessage = '';
    try {
      const result = await slideScannerApi.exportPdf(ids, detail.filename);
      downloadBlob(result.blob, result.filename);
      noticeMessage = `PDF 내보내기 완료: ${ids.length}건`;
      showPdfModal = false;
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      exportingPdf = false;
    }
  }

  function toggleSelection(detail: { id: number }) {
    selection.toggle(detail.id);
  }

  function applySearch() {
    searchQuery = searchInput.trim();
  }

  function clearSearch() {
    searchInput = '';
    searchQuery = '';
  }

  function openInEditor(detail: { id: number }) {
    onopen?.({ slideId: detail.id, sequenceIds: [...allCurrentIds] });
  }

  onMount(() => {
    mounted = true;
  });

  $effect(() => {
    void mounted;
    void statusFilter;
    void searchQuery;
    void tagFilter;
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

  <div class="flex flex-wrap items-center gap-2">
    <input
      type="text"
      class="input input-bordered input-sm w-full max-w-sm"
      placeholder="OCR 텍스트 검색"
      bind:value={searchInput}
      onkeydown={(event) => event.key === 'Enter' && applySearch()}
    />
    <button type="button" class="btn btn-outline btn-sm" onclick={applySearch}>검색</button>
    <button type="button" class="btn btn-ghost btn-sm" onclick={clearSearch} disabled={!searchQuery}>
      초기화
    </button>
    <select
      class="select select-bordered select-sm w-full max-w-[240px]"
      bind:value={tagFilter}
    >
      <option value="ALL">전체 태그</option>
      {#each availableTags as tag}
        <option value={tag}>{tag}</option>
      {/each}
    </select>
  </div>

  <BatchActionBar
    selectedCount={selection.count}
    {allSelected}
    transforming={batchTransforming}
    {archiving}
    {exportingPdf}
    disabled={slides.length === 0}
    ontoggleall={() => selection.selectAll(allCurrentIds)}
    ontransform={() => void handleBatchTransform()}
    onarchive={() => void handleArchive()}
    onexportpdf={() => (showPdfModal = true)}
  />

  {#if noticeMessage}
    <p class="rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
      {noticeMessage}
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
          ontoggle={toggleSelection}
          onopen={openInEditor}
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
  onclose={() => (showScanModal = false)}
  onsubmit={handleScanSubmit}
/>

<PdfExportModal
  open={showPdfModal}
  busy={exportingPdf}
  {selectedSlides}
  onclose={() => (showPdfModal = false)}
  onsubmit={handlePdfSubmit}
/>
