<script lang="ts">
  import { goto } from '$app/navigation';
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import { toast } from '$lib/stores/toast';
  import CornerEditor from './components/CornerEditor.svelte';
  import ImageUploader from './components/ImageUploader.svelte';
  import MobileReviewQueue from './components/MobileReviewQueue.svelte';
  import MobileSyncPanel from './components/MobileSyncPanel.svelte';
  import ResultPreview from './components/ResultPreview.svelte';
  import { slideScannerApi, type SlideDetailResponse, type SlidePoint } from '$lib/api/slide-scanner';

  let currentSlide: SlideDetailResponse | null = null;
  let points: SlidePoint[] = [];
  let resultUrl: string | null = null;
  let loading = false;
  let transforming = false;
  let errorMessage = '';
  let activeTab = 'editor';
  let mobileRefreshKey = 0;

  const tabs = [
    { id: 'editor', label: '보정 에디터' },
    { id: 'mobile-review', label: '모바일 승인 큐' }
  ];

  async function handleSelectFile(file: File) {
    const uploaded = await slideScannerApi.uploadSlide(file);
    const detail = await slideScannerApi.getSlide(uploaded.id);
    currentSlide = detail;
    points = detail.points;
  }

  async function handleSelect(event: CustomEvent<File>) {
    loading = true;
    errorMessage = '';
    resultUrl = null;
    try {
      await handleSelectFile(event.detail);
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

  async function handleMoveToEditor(event: CustomEvent<{ itemId: number; fileName: string }>) {
    loading = true;
    errorMessage = '';
    resultUrl = null;

    try {
      const file = await slideScannerApi.getMobileReviewImageFile(event.detail.itemId, event.detail.fileName);
      await handleSelectFile(file);
      await goto('?tab=editor', { replaceState: false, noScroll: true, keepFocus: true });
      toast.success('승인 큐 이미지를 보정 에디터로 불러왔습니다.');
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(errorMessage);
    } finally {
      loading = false;
    }
  }

  function handleSyncCompleted() {
    mobileRefreshKey += 1;
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
      모바일 동기화 승인 큐와 기존 보정 에디터를 하나의 페이지에서 연결해 사용합니다.
    </p>
  </header>

  <TabNav tabs={tabs} bind:activeTab variant="primary" queryParam="tab" replaceState={false} />

  {#if activeTab === 'editor'}
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
  {:else}
    <MobileSyncPanel on:syncCompleted={handleSyncCompleted} />
    <MobileReviewQueue refreshKey={mobileRefreshKey} on:moveToEditor={handleMoveToEditor} />
  {/if}
</div>
