<script lang="ts">
  import { goto } from '$app/navigation';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import { toast } from '$lib/stores/toast';

  import ImageUploader from './components/ImageUploader.svelte';
  import ResultPreview from './components/ResultPreview.svelte';
  import AspectRatioSelector from './components/AspectRatioSelector.svelte';
  import SequentialEditor from './components/SequentialEditor.svelte';
  import SlideGallery from './components/SlideGallery.svelte';
  import MobileReviewQueue from './components/MobileReviewQueue.svelte';
  import MobileSyncPanel from './components/MobileSyncPanel.svelte';

  import {
    slideScannerApi,
    DEFAULT_SLIDE_FILTERS,
    type AspectRatioValue,
    type SlideDetailResponse,
    type SlideFilterOptions,
    type SlidePoint
  } from '$lib/api/slide-scanner';

  let activeTab = 'editor';
  const tabs = [
    { id: 'editor', label: '에디터' },
    { id: 'gallery', label: '갤러리' },
    { id: 'mobile-review', label: '모바일 승인 큐' }
  ];

  let currentSlide: SlideDetailResponse | null = null;
  let points: SlidePoint[] = [];
  let resultUrl: string | null = null;
  let loading = false;
  let reviewing = false;
  let ocring = false;
  let transforming = false;
  let savingAll = false;
  let tagSaving = false;
  let inheritedApplied = false;
  let errorMessage = '';
  let infoMessage = '';
  let sequenceIds: number[] = [];
  let sequenceIndex = -1;
  let aspectRatio: AspectRatioValue = 'AUTO';
  let filters: SlideFilterOptions = { ...DEFAULT_SLIDE_FILTERS };
  let tagSuggestions: string[] = [];
  let mobileRefreshKey = 0;

  function parseError(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  function normalizeFilters(value?: SlideFilterOptions | null): SlideFilterOptions {
    const contrast =
      typeof value?.contrast === 'number' && Number.isFinite(value.contrast) ? value.contrast : 1.0;
    return {
      white_balance: Boolean(value?.white_balance),
      contrast: Math.max(0.5, Math.min(2.0, contrast)),
      document_mode: Boolean(value?.document_mode)
    };
  }

  async function loadSlideForEditor(slideId: number) {
    loading = true;
    try {
      const detail = await slideScannerApi.getSlideWithInherited(slideId);
      currentSlide = detail;

      const inheritedPoints =
        detail.inherited_points && detail.inherited_points.length === 4
          ? detail.inherited_points
          : null;
      points = inheritedPoints ?? detail.points;
      inheritedApplied = Boolean(inheritedPoints);
      aspectRatio = detail.aspect_ratio === '16:9' || detail.aspect_ratio === '4:3' ? detail.aspect_ratio : 'AUTO';
      filters = normalizeFilters(detail.filters_applied);
      await refreshTagSuggestions();
    } finally {
      loading = false;
    }
  }

  async function handleSelectFile(file: File) {
    const uploaded = await slideScannerApi.uploadSlide(file);
    const detail = await slideScannerApi.getSlide(uploaded.id);
    currentSlide = detail;
    points = detail.points;
    inheritedApplied = false;
    sequenceIds = [];
    sequenceIndex = -1;
    aspectRatio = 'AUTO';
    filters = { ...DEFAULT_SLIDE_FILTERS };
    await refreshTagSuggestions();
  }

  async function refreshTagSuggestions() {
    try {
      const result = await slideScannerApi.getTags();
      tagSuggestions = result.tags;
    } catch {
      // ignore suggestions failure; tag editing still works
    }
  }

  async function handleSelect(file: File) {
    loading = true;
    errorMessage = '';
    infoMessage = '';
    resultUrl = null;
    try {
      await handleSelectFile(file);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      loading = false;
    }
  }

  function handlePointsChange(detail: { points: SlidePoint[] }) {
    points = detail.points;
  }

  function handleFiltersChange(detail: { filters: SlideFilterOptions }) {
    filters = normalizeFilters(detail.filters);
  }

  async function handleTagChange(detail: { tag: string | null }) {
    if (!currentSlide) return;

    tagSaving = true;
    errorMessage = '';
    infoMessage = '';
    try {
      const updated = await slideScannerApi.updateSlide(currentSlide.id, {
        tag: detail.tag
      });
      currentSlide = {
        ...currentSlide,
        tag: updated.tag ?? null
      };
      infoMessage = updated.tag ? `태그 저장: ${updated.tag}` : '태그를 제거했습니다.';
      await refreshTagSuggestions();
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      tagSaving = false;
    }
  }

  async function handleTransform() {
    if (!currentSlide || points.length !== 4) return;
    transforming = true;
    errorMessage = '';
    infoMessage = '';
    try {
      await slideScannerApi.transformSlide(currentSlide.id, points, aspectRatio, filters);
      currentSlide = await slideScannerApi.getSlideWithInherited(currentSlide.id);
      resultUrl = `${slideScannerApi.getSlideResultUrl(currentSlide.id)}?t=${Date.now()}`;
      filters = normalizeFilters(currentSlide.filters_applied);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      transforming = false;
    }
  }

  async function handleOcr() {
    if (!currentSlide || points.length !== 4) return;

    ocring = true;
    errorMessage = '';
    infoMessage = '';
    try {
      await slideScannerApi.ocrSlide(currentSlide.id, ['ko', 'en']);
      currentSlide = await slideScannerApi.getSlideWithInherited(currentSlide.id);
      infoMessage = currentSlide.extracted_text?.trim()
        ? 'OCR 추출 완료'
        : 'OCR 결과 텍스트가 비어 있습니다.';
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      ocring = false;
    }
  }

  async function moveSequence(delta: number) {
    if (sequenceIndex < 0) return;
    const nextIndex = sequenceIndex + delta;
    if (nextIndex < 0 || nextIndex >= sequenceIds.length) return;

    sequenceIndex = nextIndex;
    resultUrl = null;
    infoMessage = '';
    await loadSlideForEditor(sequenceIds[nextIndex]);
  }

  async function handleReview() {
    if (!currentSlide || points.length !== 4) return;

    reviewing = true;
    errorMessage = '';
    infoMessage = '';
    try {
      await slideScannerApi.reviewSlide(currentSlide.id, points);
      if (sequenceIndex >= 0 && sequenceIndex < sequenceIds.length - 1) {
        await moveSequence(1);
      } else {
        await loadSlideForEditor(currentSlide.id);
      }
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      reviewing = false;
    }
  }

  async function handleGalleryOpen(detail: { slideId: number; sequenceIds: number[] }) {
    errorMessage = '';
    infoMessage = '';
    resultUrl = null;
    activeTab = 'editor';

    sequenceIds = detail.sequenceIds;
    sequenceIndex = sequenceIds.indexOf(detail.slideId);

    try {
      await loadSlideForEditor(detail.slideId);
    } catch (error) {
      errorMessage = parseError(error);
    }
  }

  async function handleSaveAll() {
    if (!currentSlide) return;

    savingAll = true;
    errorMessage = '';
    infoMessage = '';
    try {
      const targetIds = sequenceIds.length > 0 ? sequenceIds : [currentSlide.id];
      const result = await slideScannerApi.batchTransform(targetIds, { aspectRatio, filters });
      infoMessage =
        `전체 저장 완료: 성공 ${result.done}건, 스킵 ${result.skipped}건, 실패 ${result.failed}건`;
      currentSlide = await slideScannerApi.getSlideWithInherited(currentSlide.id);
      resultUrl = `${slideScannerApi.getSlideResultUrl(currentSlide.id)}?t=${Date.now()}`;
      filters = normalizeFilters(currentSlide.filters_applied);
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      savingAll = false;
    }
  }

  async function handleMoveToEditor(detail: { itemId: number; slideId: number }) {
    loading = true;
    errorMessage = '';
    infoMessage = '';
    resultUrl = null;

    try {
      await loadSlideForEditor(detail.slideId);
      activeTab = 'editor';
      await goto('?tab=editor', { replaceState: false, noScroll: true, keepFocus: true });
      toast.success('handoff 완료 슬라이드를 보정 에디터로 열었습니다.');
    } catch (error) {
      errorMessage = parseError(error);
      toast.error(errorMessage);
    } finally {
      loading = false;
    }
  }

  function handleSyncCompleted() {
    mobileRefreshKey += 1;
  }

  $: imageUrl = currentSlide ? slideScannerApi.getSlideImageUrl(currentSlide.id) : '';
  $: canPrev = sequenceIndex > 0;
  $: canNext = sequenceIndex >= 0 && sequenceIndex < sequenceIds.length - 1;
  $: aspectRatioLabel = aspectRatio === 'AUTO' ? 'Auto (원본 기준)' : aspectRatio;
</script>

<svelte:head>
  <title>발표 스캐너</title>
</svelte:head>

<div class="space-y-4 p-4 md:p-6">
  <PageHeader
    title="발표 사진 원근 보정 스캐너"
    subtitle="에디터, 갤러리, 모바일 승인 큐를 같은 상단 규약으로 연결해 처리합니다."
  />

  <TabNav tabs={tabs} bind:activeTab queryParam="tab" variant="primary" replaceState={false} />

  {#if activeTab === 'gallery'}
    <SlideGallery onopen={handleGalleryOpen} />
  {:else if activeTab === 'mobile-review'}
    <MobileSyncPanel onsynccompleted={handleSyncCompleted} />
    <MobileReviewQueue refreshKey={mobileRefreshKey} onmovetoeditor={handleMoveToEditor} />
  {:else}
    <ImageUploader onselect={handleSelect} />

    {#if loading}
      <p class="text-sm text-muted-foreground">이미지를 불러오는 중...</p>
    {/if}

    {#if errorMessage}
      <p class="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{errorMessage}</p>
    {/if}

    {#if infoMessage}
      <p class="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{infoMessage}</p>
    {/if}

    <div class="rounded-lg border border-border bg-card px-3 py-2">
      <AspectRatioSelector
        value={aspectRatio}
        disabled={loading || transforming || savingAll}
        onchange={(detail) => (aspectRatio = detail.value)}
      />
    </div>

    <SequentialEditor
      slide={currentSlide}
      {points}
      {imageUrl}
      {canPrev}
      {canNext}
      {reviewing}
      {ocring}
      transforming={transforming || savingAll}
      inheritedApplied={inheritedApplied}
      {aspectRatioLabel}
      extractedText={currentSlide?.extracted_text ?? ''}
      {filters}
      tag={currentSlide?.tag ?? null}
      {tagSuggestions}
      {tagSaving}
      onchangepoints={handlePointsChange}
      onchangefilters={handleFiltersChange}
      onchangetag={(detail) => void handleTagChange(detail)}
      onprev={() => void moveSequence(-1)}
      onnext={() => void moveSequence(1)}
      onocr={() => void handleOcr()}
      onreview={() => void handleReview()}
      ontransform={() => void handleTransform()}
      onsaveall={() => void handleSaveAll()}
    />

    <ResultPreview {resultUrl} />
  {/if}
</div>
