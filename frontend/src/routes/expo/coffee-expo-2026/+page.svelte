<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page as pageStore } from '$app/stores';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import type { ExpoBooth, ExpoMapDocument, ExpoMapMeta } from '$lib/types';
  import { expoApi } from '$lib/api';
  import BoothDetailPanel from '../components/BoothDetailPanel.svelte';
  import ExpoFilterBar from '../components/ExpoFilterBar.svelte';
  import ExpoMapCanvas from '../components/ExpoMapCanvas.svelte';
  import expoData from './expo-data.json';

  const expo = expoData as ExpoMapDocument;
  // [slug] 승격 시 이동 대상: expo-data import, route 경로, author/preview 링크 참조부.

  /** admin 업로드 override 메타데이터. null이면 static fallback 사용 */
  let mapOverride = $state<ExpoMapMeta | null>(null);

  /** 실제 렌더에 사용할 map (override가 있으면 imageSrc/width/height 치환) */
  const effectiveMap = $derived<ExpoMapDocument['map']>(
    mapOverride?.image_url
      ? {
          ...expo.map,
          imageSrc: mapOverride.image_url,
          width: mapOverride.width ?? expo.map.width,
          height: mapOverride.height ?? expo.map.height,
        }
      : expo.map
  );

  let imageFailed = $state(false);
  let liveMessage = $state('');
  let searchQuery = $state('');
  let selectedBoothId = $state<string | null>(null);
  let selectedSlotId = $state<string | null>(null);
  let lastUrlKey = $state('');
  let skipNextUrlSync = $state(false);

  function boothMatches(booth: ExpoBooth, slotId: string | null, query: string) {
    const normalizedQuery = query.trim().toLowerCase();
    const matchesQuery = normalizedQuery.length === 0 ||
      booth.id.toLowerCase().includes(normalizedQuery) ||
      booth.name.toLowerCase().includes(normalizedQuery) ||
      booth.brand?.toLowerCase().includes(normalizedQuery) ||
      booth.tags?.some((tag) => tag.toLowerCase().includes(normalizedQuery));

    if (!matchesQuery) {
      return false;
    }

    if (!slotId) {
      return true;
    }

    return (booth.events ?? []).some((event) => event.slotIds.includes(slotId));
  }

  function findValidBoothId(candidate: string | null) {
    if (!candidate) {
      return null;
    }

    return expo.booths.some((booth) => booth.id === candidate) ? candidate : null;
  }

  function findValidSlotId(candidate: string | null) {
    if (!candidate) {
      return null;
    }

    return expo.timeSlots.some((slot) => slot.id === candidate) ? candidate : null;
  }

  function applyUrlState() {
    selectedBoothId = findValidBoothId($pageStore.url.searchParams.get('booth'));
    selectedSlotId = findValidSlotId($pageStore.url.searchParams.get('slot'));
  }

  function syncUrl() {
    const url = new URL($pageStore.url);

    if (selectedBoothId) {
      url.searchParams.set('booth', selectedBoothId);
    } else {
      url.searchParams.delete('booth');
    }

    if (selectedSlotId) {
      url.searchParams.set('slot', selectedSlotId);
    } else {
      url.searchParams.delete('slot');
    }

    const nextKey = `${url.pathname}?${url.searchParams.toString()}`;
    if (nextKey === lastUrlKey) {
      return;
    }

    skipNextUrlSync = true;
    lastUrlKey = nextKey;
    goto(url.toString(), {
      replaceState: true,
      keepFocus: true,
      noScroll: true
    });
  }

  const matchedBooths = $derived.by(() =>
    expo.booths.filter((booth) => boothMatches(booth, selectedSlotId, searchQuery))
  );
  const matchedBoothIds = $derived.by(() => new Set(matchedBooths.map((booth) => booth.id)));
  const selectedBooth = $derived.by(
    () => expo.booths.find((booth) => booth.id === selectedBoothId) ?? null
  );

  function handleReset() {
    searchQuery = '';
    selectedSlotId = null;
    liveMessage = '필터가 초기화되었습니다';
    syncUrl();
  }

  function handleSelectSlot(slotId: string | null) {
    selectedSlotId = slotId;
    liveMessage = slotId
      ? `${expo.timeSlots.find((slot) => slot.id === slotId)?.label ?? slotId} 필터 적용`
      : '전체 시간 필터 적용';
    if (selectedBooth && !boothMatches(selectedBooth, slotId, searchQuery)) {
      selectedBoothId = null;
    }
    syncUrl();
  }

  function handleSearchChange(value: string) {
    searchQuery = value;
    if (selectedBooth && !boothMatches(selectedBooth, selectedSlotId, value)) {
      selectedBoothId = null;
      syncUrl();
    }
  }

  function handleSelectBooth(boothId: string) {
    selectedBoothId = boothId;
    liveMessage = `${boothId} 선택됨`;
    syncUrl();
  }

  function closeDetail() {
    selectedBoothId = null;
    liveMessage = '부스 선택이 해제되었습니다';
    syncUrl();
  }

  $effect(() => {
    const nextKey = `${$pageStore.url.pathname}?${$pageStore.url.searchParams.toString()}`;
    if (skipNextUrlSync) {
      skipNextUrlSync = false;
      return;
    }
    if (nextKey === lastUrlKey) {
      return;
    }

    lastUrlKey = nextKey;
    applyUrlState();
  });

  onMount(() => {
    // admin upload override가 있으면 static imageSrc를 runtime으로 교체
    expoApi.getMapMeta(expo.slug).then((meta) => {
      if (meta?.image_url) {
        mapOverride = meta;
      }
    }).catch(() => {
      // 조회 실패 시 무시하고 static fallback 유지
    });
  });
</script>

<svelte:head>
  <title>{expo.title} 부스맵</title>
  <meta name="description" content="커피엑스포 2026 현장 부스 배치도와 이벤트 시간을 공개합니다." />
  <meta name="theme-color" content={expo.themeColor ?? '#9a3412'} />
</svelte:head>

<main class="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 bg-[linear-gradient(180deg,_#fff9ef_0%,_#f6f3ec_100%)] px-4 py-6 lg:px-6">
  <PageHeader title={expo.title} subtitle={`${expo.venue} · ${expo.dateRange}`} />

  <section class="rounded-[32px] border border-white/70 bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.2),_transparent_28%),linear-gradient(135deg,_rgba(255,255,255,0.94),_rgba(255,247,237,0.92))] p-6 shadow-[0_30px_80px_rgba(148,163,184,0.14)]">
    <div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div class="space-y-6">
        <div class="space-y-3">
          <p class="text-xs font-semibold uppercase tracking-[0.3em] text-amber-700">Public Floor Guide</p>
          <h2 class="text-3xl font-semibold tracking-tight text-slate-900 lg:text-5xl">
            현장 동선은 가볍게, 부스 정보는 바로.
          </h2>
          <p class="max-w-3xl text-sm leading-7 text-slate-600 lg:text-base">
            온라인 이벤트 페이지와 분리된 공개 전용 부스맵입니다. 부스 핀을 눌러 상세 정보와 현장 이벤트 시간을 확인하고,
            시간 슬롯별로 빠르게 탐색할 수 있습니다.
          </p>
        </div>

        <ExpoFilterBar
          matchCount={matchedBooths.length}
          searchQuery={searchQuery}
          selectedSlotId={selectedSlotId}
          slotOptions={expo.timeSlots}
          onReset={handleReset}
          onSearchChange={handleSearchChange}
          onSelectSlot={handleSelectSlot}
        />

        {#if imageFailed}
          <section class="rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
            <div class="mb-4">
              <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Degraded Mode</p>
              <h2 class="mt-2 text-xl font-semibold text-slate-900">배치도 이미지를 불러오지 못했습니다</h2>
            </div>

            {#if matchedBooths.length > 0}
              <div class="grid gap-3 md:grid-cols-2">
                {#each matchedBooths as booth}
                  <button
                    type="button"
                    class="rounded-[24px] border border-slate-200 bg-slate-50 p-4 text-left transition hover:border-amber-500 hover:bg-white"
                    onclick={() => handleSelectBooth(booth.id)}
                  >
                    <p class="text-xs font-semibold uppercase tracking-[0.2em] text-amber-700">{booth.id}</p>
                    <h3 class="mt-2 text-lg font-semibold text-slate-900">{booth.name}</h3>
                    {#if booth.brand}
                      <p class="mt-1 text-sm text-slate-500">{booth.brand}</p>
                    {/if}
                    {#if booth.description}
                      <p class="mt-3 text-sm leading-6 text-slate-600">{booth.description}</p>
                    {/if}
                  </button>
                {/each}
              </div>
            {:else}
              <div class="rounded-[24px] border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
                현재 필터에 맞는 부스가 없습니다.
              </div>
            {/if}
          </section>
        {:else}
          <ExpoMapCanvas
            map={effectiveMap}
            booths={expo.booths}
            matchedBoothIds={matchedBoothIds}
            selectedBoothId={selectedBoothId}
            onImageError={() => {
              imageFailed = true;
            }}
            onSelectBooth={handleSelectBooth}
          />
        {/if}

        <section class="rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm lg:hidden">
          <div class="mb-4">
            <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Matched Booths</p>
            <h2 class="mt-2 text-xl font-semibold text-slate-900">모바일 부스 리스트</h2>
          </div>
          <div class="flex gap-3 overflow-x-auto pb-2">
            {#if matchedBooths.length > 0}
              {#each matchedBooths as booth}
                <button
                  type="button"
                  class="min-w-[220px] rounded-[24px] border p-4 text-left transition"
                  class:border-amber-500={selectedBoothId === booth.id}
                  class:bg-amber-50={selectedBoothId === booth.id}
                  class:border-slate-200={selectedBoothId !== booth.id}
                  class:bg-slate-50={selectedBoothId !== booth.id}
                  onclick={() => handleSelectBooth(booth.id)}
                >
                  <p class="text-xs font-semibold uppercase tracking-[0.2em] text-amber-700">{booth.id}</p>
                  <h3 class="mt-2 text-base font-semibold text-slate-900">{booth.name}</h3>
                  {#if booth.brand}
                    <p class="mt-1 text-sm text-slate-500">{booth.brand}</p>
                  {/if}
                </button>
              {/each}
            {:else}
              <div class="w-full rounded-[24px] border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
                현재 필터에 맞는 부스가 없습니다.
              </div>
            {/if}
          </div>
        </section>
      </div>

      <div class="space-y-4">
        <section class="hidden rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm lg:block">
          <div class="mb-4">
            <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Matched Booths</p>
            <h2 class="mt-2 text-xl font-semibold text-slate-900">선택 가능한 부스</h2>
          </div>

          {#if matchedBooths.length > 0}
            <div class="space-y-2">
              {#each matchedBooths as booth}
                <button
                  type="button"
                  class="w-full rounded-[22px] border px-4 py-3 text-left transition"
                  class:border-amber-500={selectedBoothId === booth.id}
                  class:bg-amber-50={selectedBoothId === booth.id}
                  class:border-slate-200={selectedBoothId !== booth.id}
                  class:bg-slate-50={selectedBoothId !== booth.id}
                  onclick={() => handleSelectBooth(booth.id)}
                >
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <p class="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">{booth.id}</p>
                      <p class="mt-1 text-sm font-semibold text-slate-900">{booth.name}</p>
                    </div>
                    <span class="text-xs text-slate-500">{booth.events?.length ?? 0} events</span>
                  </div>
                </button>
              {/each}
            </div>
          {:else}
            <div class="rounded-[24px] border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
              현재 필터에 맞는 부스가 없습니다.
            </div>
          {/if}
        </section>

        <BoothDetailPanel booth={selectedBooth} onClose={closeDetail} />
      </div>
    </div>
  </section>

  <p class="sr-only" aria-live="polite">{liveMessage}</p>
</main>
