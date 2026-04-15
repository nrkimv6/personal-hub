<script lang="ts">
  import { onMount } from 'svelte';
  import type { ExpoBooth, ExpoDraftBooth, ExpoMapDocument } from '$lib/types';
  import BoothAuthorPanel from './BoothAuthorPanel.svelte';

  interface Props {
    existingBooths: ExpoBooth[];
    map: ExpoMapDocument['map'];
    onSaveDrafts: (drafts: ExpoDraftBooth[]) => Promise<void> | void;
    previewHref: string;
    previewLabel?: string;
    saveButtonLabel?: string;
    slug: string;
    title: string;
  }

  let {
    existingBooths,
    map,
    onSaveDrafts,
    previewHref,
    previewLabel = '공개 부스맵 열기',
    saveButtonLabel = 'JSON 복사',
    slug,
    title
  }: Props = $props();

  let isMobileViewport = $state(false);

  onMount(() => {
    const media = window.matchMedia('(max-width: 767px)');
    const updateViewport = () => {
      isMobileViewport = media.matches;
    };

    updateViewport();
    media.addEventListener('change', updateViewport);

    return () => {
      media.removeEventListener('change', updateViewport);
    };
  });
</script>

<section class="space-y-5 rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
  <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Expo Workspace</p>
      <h2 class="mt-2 text-2xl font-semibold text-slate-900">{title} 좌표 작업</h2>
      <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
        draft는 브라우저 로컬에만 저장됩니다. 공개 route와 동일한 데이터 계약을 쓰되, 저장 방식은 현재
        `copy-json` 단계까지만 열어둡니다.
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
      onSaveDrafts={onSaveDrafts}
      saveButtonLabel={saveButtonLabel}
      slug={slug}
    />
  {/if}
</section>
