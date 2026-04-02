<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';

  import CornerEditor from './components/CornerEditor.svelte';
  import ImageUploader from './components/ImageUploader.svelte';
  import ResultPreview from './components/ResultPreview.svelte';
  import SlideGallery from './components/SlideGallery.svelte';

  import { slideScannerApi, type SlideDetailResponse, type SlidePoint } from '$lib/api/slide-scanner';

  let activeTab = 'editor';
  const tabs = [
    { id: 'editor', label: '에디터' },
    { id: 'gallery', label: '갤러리' }
  ];

  let currentSlide: SlideDetailResponse | null = null;
  let points: SlidePoint[] = [];
  let resultUrl: string | null = null;
  let loading = false;
  let transforming = false;
  let errorMessage = '';

  async function handleSelect(event: CustomEvent<File>) {
    loading = true;
    errorMessage = '';
    resultUrl = null;
    try {
      const uploaded = await slideScannerApi.uploadSlide(event.detail);
      const detail = await slideScannerApi.getSlide(uploaded.id);
      currentSlide = detail;
      points = detail.points;
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error);
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
    try {
      await slideScannerApi.transformSlide(currentSlide.id, points);
      currentSlide = await slideScannerApi.getSlide(currentSlide.id);
      resultUrl = `${slideScannerApi.getSlideResultUrl(currentSlide.id)}?t=${Date.now()}`;
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error);
    } finally {
      transforming = false;
    }
  }

  $: imageUrl = currentSlide ? slideScannerApi.getSlideImageUrl(currentSlide.id) : '';
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
    <SlideGallery />
  {:else}
    <ImageUploader on:select={handleSelect} />

    {#if loading}
      <p class="text-sm text-muted-foreground">이미지 업로드 및 자동 검출 중...</p>
    {/if}

    {#if errorMessage}
      <p class="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">{errorMessage}</p>
    {/if}

    {#if currentSlide}
      <section class="space-y-3 rounded-xl border border-border bg-card p-4">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold">{currentSlide.file_name}</h2>
          <button
            type="button"
            class="btn btn-primary"
            onclick={handleTransform}
            disabled={transforming || points.length !== 4}
          >
            {transforming ? '변환 중...' : '보정 실행'}
          </button>
        </div>
        <CornerEditor imageUrl={imageUrl} {points} on:change={handlePointsChange} />
      </section>
    {/if}

    <ResultPreview {resultUrl} />
  {/if}
</div>
