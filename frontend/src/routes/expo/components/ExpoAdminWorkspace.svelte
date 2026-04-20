<script lang="ts">
  import { browser } from '$app/environment';
  import { onMount } from 'svelte';
  import { toast } from '$lib/stores/toast';
  import { expoApi } from '$lib/api';
  import type {
    ExpoBooth,
    ExpoDraftBooth,
    ExpoMapDocument,
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

  onMount(() => {
    const media = window.matchMedia('(max-width: 767px)');
    const updateViewport = () => {
      isMobileViewport = media.matches;
    };
    let pollTimer: number | null = null;

    updateViewport();
    media.addEventListener('change', updateViewport);
    refreshStatuses();
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
      map={map}
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
