<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import type { ExpoMapDocument } from '$lib/types';
  import BoothAuthorPanel from '../../components/BoothAuthorPanel.svelte';
  import expoData from '../expo-data.json';

  const expo = expoData as ExpoMapDocument;

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

<svelte:head>
  <title>{expo.title} Author Helper</title>
  <meta name="robots" content="noindex" />
</svelte:head>

<main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 bg-[linear-gradient(180deg,_#fffaf2_0%,_#f6f1e8_100%)] px-4 py-6 lg:px-6">
  <PageHeader title={`${expo.title} 좌표 작성`} subtitle="admin 모드 전용 author helper" />

  {#if isMobileViewport}
    <section class="rounded-[28px] border border-slate-200 bg-white/96 p-8 text-center shadow-sm">
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Desktop Only</p>
      <h1 class="mt-2 text-2xl font-semibold text-slate-900">PC에서 열어주세요</h1>
      <p class="mt-3 text-sm leading-6 text-slate-600">
        좌표 미세 조정은 마우스 정밀도가 필요합니다. author helper는 데스크톱 해상도 기준으로만 지원합니다.
      </p>
    </section>
  {:else}
    <BoothAuthorPanel existingBooths={expo.booths} map={expo.map} slug={expo.slug} />
  {/if}
</main>
