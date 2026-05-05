<script lang="ts">
  import { browser } from '$app/environment';
  import { onMount } from 'svelte';
  import { toast } from '$lib/stores/toast';
  import { expoApi } from '$lib/api';
  import type {
    ExpoBooth,
    ExpoDraftBooth,
    ExpoMapDocument,
    ExpoMapMeta,
    ExpoCollectionStatusResponse,
    ExpoPipelineStatusResponse,
  } from '$lib/types';
  import BoothAuthorPanel from './BoothAuthorPanel.svelte';
  import ExpoCollectionStatusSection from './ExpoCollectionStatusSection.svelte';
  import ExpoPipelineStatusSection from './ExpoPipelineStatusSection.svelte';
  import { buildExpoExportPayload, copyExpoExportPayloadToClipboard } from '../utils/authorDraft';

  interface Props {
    existingBooths: ExpoBooth[];
    map: ExpoMapDocument['map'];
    previewHref: string;
    previewLabel?: string;
    saveButtonLabel?: string;
    slug: string;
    title: string;
  }

  let {
    existingBooths,
    map,
    previewHref,
    previewLabel = '공개 부스맵 열기',
    saveButtonLabel = 'Export JSON',
    slug,
    title
  }: Props = $props();

  let isMobileViewport = $state(false);
  let currentDrafts = $state<ExpoDraftBooth[]>([]);
  let pipelineStatus = $state<ExpoPipelineStatusResponse | null>(null);
  let collectionStatus = $state<ExpoCollectionStatusResponse | null>(null);
  let statusLoading = $state(true);
  let statusError = $state<string | null>(null);
  let exportPending = $state(false);

  // 배치도 업로드 상태
  let mapMeta = $state<ExpoMapMeta | null>(null);
  let mapMetaLoading = $state(false);
  let uploadPending = $state(false);
  let uploadError = $state<string | null>(null);
  let uploadSuccess = $state(false);
  let fileInput: HTMLInputElement | null = null;

  /** 현재 사이드바에 표시할 map imageSrc (override가 있으면 override, 없으면 static fallback) */
  const effectiveMapSrc = $derived(mapMeta?.image_url ?? map.imageSrc);
  const effectiveMap = $derived<ExpoMapDocument['map']>({
    ...map,
    imageSrc: effectiveMapSrc,
    width: mapMeta?.width ?? map.width,
    height: mapMeta?.height ?? map.height,
  });

  async function refreshStatuses() {
    try {
      statusError = null;
      const [pipeline, collection] = await Promise.all([
        expoApi.getPipelineStatus(slug),
        expoApi.getCollectionStatus(slug)
      ]);
      pipelineStatus = pipeline;
      collectionStatus = collection;
    } catch (error) {
      statusError = error instanceof Error ? error.message : 'expo 상태를 불러오지 못했습니다.';
    } finally {
      statusLoading = false;
    }
  }

  async function refreshMapMeta() {
    mapMetaLoading = true;
    try {
      mapMeta = await expoApi.getMapMeta(slug);
    } catch {
      // 조회 실패 시 override 없음으로 처리
      mapMeta = null;
    } finally {
      mapMetaLoading = false;
    }
  }

  async function handleExportDrafts(drafts: ExpoDraftBooth[] = currentDrafts) {
    if (!browser || drafts.length === 0) {
      toast.warning('복사할 좌표 draft가 없습니다.');
      return;
    }

    exportPending = true;

    try {
      const payload = buildExpoExportPayload(slug, drafts, title);
      await copyExpoExportPayloadToClipboard(payload);
      await expoApi.recordExport(slug, payload);
      await refreshStatuses();
      toast.success(`${drafts.length}개 draft를 복사하고 export 기록을 저장했습니다.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'export 저장에 실패했습니다.';
      toast.error(message);
    } finally {
      exportPending = false;
    }
  }

  async function handleUpload() {
    if (!fileInput?.files?.length) {
      toast.warning('파일을 선택해주세요.');
      return;
    }

    const file = fileInput.files[0];
    uploadPending = true;
    uploadError = null;
    uploadSuccess = false;

    try {
      const result = await expoApi.uploadMap(slug, file);
      mapMeta = result;
      uploadSuccess = true;
      toast.success('배치도 이미지가 업로드되었습니다.');
      // 파일 input 초기화
      if (fileInput) fileInput.value = '';
    } catch (error) {
      uploadError = error instanceof Error ? error.message : '업로드에 실패했습니다.';
      toast.error(uploadError);
    } finally {
      uploadPending = false;
    }
  }

  async function handleDeleteOverride() {
    if (!mapMeta?.image_url) return;
    try {
      await expoApi.deleteMapOverride(slug);
      mapMeta = null;
      uploadSuccess = false;
      toast.success('배치도 override가 삭제되었습니다. 기본 이미지로 복원됩니다.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '삭제에 실패했습니다.');
    }
  }

  onMount(() => {
    const media = window.matchMedia('(max-width: 767px)');
    const updateViewport = () => {
      isMobileViewport = media.matches;
    };
    let pollTimer: number | null = null;

    updateViewport();
    media.addEventListener('change', updateViewport);
    refreshStatuses();
    refreshMapMeta();
    pollTimer = window.setInterval(() => {
      void refreshStatuses();
    }, 30000);

    return () => {
      media.removeEventListener('change', updateViewport);
      if (pollTimer !== null) {
        window.clearInterval(pollTimer);
      }
    };
  });
</script>

<section class="space-y-5 rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
  <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Expo Workspace</p>
      <h2 class="mt-2 text-2xl font-semibold text-slate-900">{title} 좌표 작업</h2>
      <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
        이 화면은 monitor-page 내부 제작 도구입니다. draft는 브라우저 local에만 저장되고, export JSON을
        admin-tools 검수 표면으로 넘기는 역할까지만 담당합니다.
      </p>
    </div>

    <a
      href={previewHref}
      target="_blank"
      rel="noreferrer"
      class="inline-flex rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
    >
      {previewLabel}
    </a>
  </div>

  <!-- 배치도 업로드 패널 -->
  <div class="rounded-[24px] border border-slate-200 bg-slate-50/80 p-5">
    <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">배치도 이미지</p>
    <h3 class="mt-2 text-lg font-semibold text-slate-900">배치도 업로드</h3>
    <p class="mt-1 text-sm text-slate-500">
      PNG / JPG / WebP 형식, 최대 20 MB. 업로드 즉시 공개 부스맵에 반영됩니다.
    </p>

    <!-- 현재 override 상태 -->
    {#if mapMetaLoading}
      <p class="mt-3 text-sm text-slate-400">업로드 상태 확인 중...</p>
    {:else if mapMeta?.image_url}
      <div class="mt-3 flex flex-wrap items-start gap-4">
        <img
          src={mapMeta.image_url}
          alt="현재 배치도 preview"
          class="h-24 w-auto rounded-2xl border border-slate-200 object-contain bg-white"
        />
        <div class="flex-1 space-y-1 text-sm">
          <p class="font-semibold text-green-700">업로드된 배치도 사용 중</p>
          {#if mapMeta.width && mapMeta.height}
            <p class="text-slate-500">{mapMeta.width} × {mapMeta.height}px</p>
          {/if}
          {#if mapMeta.uploaded_at}
            <p class="text-slate-500">
              업로드: {new Date(mapMeta.uploaded_at).toLocaleString('ko-KR')}
            </p>
          {/if}
          <button
            type="button"
            class="mt-2 rounded-full border border-rose-300 px-3 py-1 text-xs font-semibold text-rose-700 transition hover:bg-rose-50"
            onclick={handleDeleteOverride}
          >
            override 삭제 (기본 이미지 복원)
          </button>
        </div>
      </div>
    {:else}
      <p class="mt-3 text-sm text-slate-500">현재 기본 배치도 이미지를 사용 중입니다.</p>
    {/if}

    <!-- 업로드 form -->
    <div class="mt-4 flex flex-wrap items-center gap-3">
      <input
        bind:this={fileInput}
        type="file"
        accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
        class="text-sm text-slate-600 file:mr-3 file:rounded-full file:border file:border-slate-300 file:bg-white file:px-4 file:py-1.5 file:text-sm file:font-semibold file:text-slate-700 file:transition hover:file:bg-slate-50"
      />
      <button
        type="button"
        class="rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-amber-700 disabled:opacity-50"
        disabled={uploadPending}
        onclick={handleUpload}
      >
        {uploadPending ? '업로드 중...' : '업로드'}
      </button>
    </div>

    {#if uploadError}
      <p class="mt-2 text-sm text-rose-600">{uploadError}</p>
    {/if}
    {#if uploadSuccess}
      <p class="mt-2 text-sm text-green-600">업로드 완료. 공개 페이지에서 새 이미지를 확인하세요.</p>
    {/if}
  </div>

  {#if isMobileViewport}
    <section class="rounded-[28px] border border-slate-200 bg-slate-50/90 p-8 text-center shadow-sm">
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Desktop Only</p>
      <h3 class="mt-2 text-2xl font-semibold text-slate-900">PC에서 열어주세요</h3>
      <p class="mt-3 text-sm leading-6 text-slate-600">
        좌표 미세 조정은 마우스 정밀도가 필요합니다. expo workspace는 데스크톱 해상도 기준으로만 지원합니다.
      </p>
    </section>
  {:else}
    <BoothAuthorPanel
      existingBooths={existingBooths}
      map={effectiveMap}
      onDraftsChange={(drafts) => {
        currentDrafts = drafts;
      }}
      onSaveDrafts={handleExportDrafts}
      saveButtonLabel={saveButtonLabel}
      slug={slug}
      title={title}
    />
  {/if}
</section>

{#if statusError && !pipelineStatus && !collectionStatus}
  <p class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{statusError}</p>
{/if}

<div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
  <ExpoPipelineStatusSection
    status={pipelineStatus}
    loading={statusLoading}
    error={statusError}
  />
  <ExpoCollectionStatusSection
    status={collectionStatus}
    loading={statusLoading}
    error={statusError}
    draftCount={currentDrafts.length}
    exportPending={exportPending}
    onExport={handleExportDrafts}
  />
</div>
