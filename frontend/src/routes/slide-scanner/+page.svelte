<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';

  import ImageUploader from './components/ImageUploader.svelte';
  import ResultPreview from './components/ResultPreview.svelte';
  import AspectRatioSelector from './components/AspectRatioSelector.svelte';
  import SequentialEditor from './components/SequentialEditor.svelte';
  import SlideGallery from './components/SlideGallery.svelte';

  import {
    slideScannerApi,
    type AspectRatioValue,
    type SlideDetailResponse,
    type SlidePoint
  } from '$lib/api/slide-scanner';

  let activeTab = 'editor';
  const tabs = [
    { id: 'editor', label: '에디터' },
    { id: 'gallery', label: '갤러리' }
  ];

  let currentSlide: SlideDetailResponse | null = null;
  let points: SlidePoint[] = [];
  let resultUrl: string | null = null;
  let loading = false;
  let reviewing = false;
  let transforming = false;
  let savingAll = false;
  let inheritedApplied = false;
  let errorMessage = '';
  let infoMessage = '';
  let sequenceIds: number[] = [];
  let sequenceIndex = -1;
  let aspectRatio: AspectRatioValue = 'AUTO';

  function parseError(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
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
    } finally {
      loading = false;
    }
  }

  async function handleSelect(event: CustomEvent<File>) {
    loading = true;
    errorMessage = '';
    infoMessage = '';
    resultUrl = null;
    try {
      const uploaded = await slideScannerApi.uploadSlide(event.detail);
      const detail = await slideScannerApi.getSlide(uploaded.id);
      currentSlide = detail;
      points = detail.points;
      inheritedApplied = false;
      sequenceIds = [];
      sequenceIndex = -1;
      aspectRatio = 'AUTO';
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      loading = false;
    }
  }

  function handlePointsChange(event: CustomEvent<{ points: SlidePoint[] }>) {
    points = event.detail.points;
  }

  async function handleTransform() {
    if (!currentSlide || points.length !== 4) return;
    transforming = true;
    errorMessage = '';
    infoMessage = '';
    try {
      await slideScannerApi.transformSlide(currentSlide.id, points, aspectRatio);
      currentSlide = await slideScannerApi.getSlideWithInherited(currentSlide.id);
      resultUrl = `${slideScannerApi.getSlideResultUrl(currentSlide.id)}?t=${Date.now()}`;
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      transforming = false;
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

  async function handleGalleryOpen(event: CustomEvent<{ slideId: number; sequenceIds: number[] }>) {
    errorMessage = '';
    infoMessage = '';
    resultUrl = null;
    activeTab = 'editor';

    sequenceIds = event.detail.sequenceIds;
    sequenceIndex = sequenceIds.indexOf(event.detail.slideId);

    try {
      await loadSlideForEditor(event.detail.slideId);
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
      const result = await slideScannerApi.batchTransform(targetIds, { aspectRatio });
      infoMessage =
        `전체 저장 완료: 성공 ${result.done}건, 스킵 ${result.skipped}건, 실패 ${result.failed}건`;
      currentSlide = await slideScannerApi.getSlideWithInherited(currentSlide.id);
      resultUrl = `${slideScannerApi.getSlideResultUrl(currentSlide.id)}?t=${Date.now()}`;
    } catch (error) {
      errorMessage = parseError(error);
    } finally {
      savingAll = false;
    }
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
  <header>
    <h1 class="text-xl font-semibold">발표 사진 원근 보정 스캐너</h1>
    <p class="mt-1 text-sm text-muted-foreground">
      에디터/갤러리 탭으로 단건 보정과 대량 스캔 워크플로우를 모두 처리합니다.
    </p>
  </header>

  <TabNav tabs={tabs} bind:activeTab queryParam="tab" variant="primary" />

  {#if activeTab === 'gallery'}
    <SlideGallery on:open={handleGalleryOpen} />
  {:else}
    <ImageUploader on:select={handleSelect} />

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
        on:change={(event) => (aspectRatio = event.detail.value)}
      />
    </div>

    <SequentialEditor
      slide={currentSlide}
      {points}
      {imageUrl}
      {canPrev}
      {canNext}
      {reviewing}
      transforming={transforming || savingAll}
      inheritedApplied={inheritedApplied}
      {aspectRatioLabel}
      on:changePoints={handlePointsChange}
      on:prev={() => void moveSequence(-1)}
      on:next={() => void moveSequence(1)}
      on:review={() => void handleReview()}
      on:transform={() => void handleTransform()}
      on:saveAll={() => void handleSaveAll()}
    />

    <ResultPreview {resultUrl} />
  {/if}
</div>
