<script lang="ts">
  import type { ExpoBooth } from '$lib/types';

  interface Props {
    booth: ExpoBooth | null;
    onClose: () => void;
  }

  let { booth, onClose }: Props = $props();
  let mobileTitleId = $derived(booth ? `expo-booth-sheet-title-${booth.id}` : 'expo-booth-sheet-title');

  $effect(() => {
    if (typeof window === 'undefined' || typeof document === 'undefined') {
      return;
    }

    if (!booth || !window.matchMedia('(max-width: 1023px)').matches) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  });
</script>

<svelte:window
  onkeydown={(event) => {
    if (event.key === 'Escape' && booth) {
      onClose();
    }
  }}
/>

<aside class="hidden h-full min-h-[480px] flex-col rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm lg:flex">
  {#if booth}
    <div class="space-y-4">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">{booth.id}</p>
        <h2 class="mt-2 text-2xl font-semibold text-slate-900">{booth.name}</h2>
        {#if booth.brand}
          <p class="mt-1 text-sm text-slate-500">{booth.brand}</p>
        {/if}
      </div>

      {#if booth.description}
        <p class="rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700">{booth.description}</p>
      {/if}

      {#if booth.tags?.length}
        <div class="flex flex-wrap gap-2">
          {#each booth.tags as tag}
            <span class="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-900">{tag}</span>
          {/each}
        </div>
      {/if}

      {#if booth.link}
        <a
          href={booth.link}
          target="_blank"
          rel="noreferrer"
          class="inline-flex rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
        >
          브랜드 링크 열기
        </a>
      {/if}

      <section class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <h3 class="text-sm font-semibold text-slate-900">부스 이벤트 시간</h3>
        {#if booth.events?.length}
          <ul class="mt-3 space-y-3">
            {#each booth.events as event}
              <li class="rounded-2xl bg-white px-4 py-3">
                <p class="text-sm font-semibold text-slate-900">{event.title}</p>
                <p class="mt-1 text-xs font-medium text-amber-700">
                  {event.start} - {event.end}
                </p>
                {#if event.description}
                  <p class="mt-2 text-sm text-slate-600">{event.description}</p>
                {/if}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="mt-3 text-sm text-slate-500">현재 등록된 현장 이벤트 시간이 없습니다.</p>
        {/if}
      </section>
    </div>
  {:else}
    <div class="flex h-full items-center justify-center rounded-[24px] border border-dashed border-slate-300 bg-slate-50 px-6 text-center text-sm leading-6 text-slate-500">
      지도의 핀 또는 부스 목록을 선택하면 상세 정보가 이 패널에 표시됩니다.
    </div>
  {/if}
</aside>

{#if booth}
  <div class="fixed inset-0 z-40 bg-slate-950/35 lg:hidden" onclick={onClose}></div>
  <section
    class="fixed inset-x-0 bottom-0 z-50 overflow-y-auto rounded-t-[32px] border border-slate-200 bg-white px-5 pb-5 pt-3 shadow-[0_-18px_50px_rgba(15,23,42,0.22)] overscroll-contain lg:hidden"
    role="dialog"
    aria-modal="true"
    aria-labelledby={mobileTitleId}
    style="padding-left: calc(1.25rem + env(safe-area-inset-left)); padding-right: calc(1.25rem + env(safe-area-inset-right)); padding-bottom: calc(1.25rem + env(safe-area-inset-bottom)); max-height: min(82vh, calc(100vh - env(safe-area-inset-top) - 0.75rem));"
  >
    <div class="mx-auto h-1.5 w-14 rounded-full bg-slate-200" aria-hidden="true"></div>

    <div class="mt-4 flex items-start justify-between gap-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">{booth.id}</p>
        <h2 class="mt-2 text-xl font-semibold text-slate-900" id={mobileTitleId}>{booth.name}</h2>
        {#if booth.brand}
          <p class="mt-1 text-sm text-slate-500">{booth.brand}</p>
        {/if}
      </div>
      <button
        type="button"
        class="rounded-full border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700"
        onclick={onClose}
      >
        닫기
      </button>
    </div>

    {#if booth.description}
      <p class="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700">{booth.description}</p>
    {/if}

    {#if booth.tags?.length}
      <div class="mt-4 flex flex-wrap gap-2">
        {#each booth.tags as tag}
          <span class="rounded-full bg-amber-50 px-3 py-1 text-xs font-medium text-amber-900">{tag}</span>
        {/each}
      </div>
    {/if}

    {#if booth.link}
      <a
        href={booth.link}
        target="_blank"
        rel="noreferrer"
        class="mt-4 inline-flex rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
      >
        브랜드 링크 열기
      </a>
    {/if}

    <section class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <h3 class="text-sm font-semibold text-slate-900">부스 이벤트 시간</h3>
      {#if booth.events?.length}
        <ul class="mt-3 space-y-3">
          {#each booth.events as event}
            <li class="rounded-2xl bg-white px-4 py-3">
              <p class="text-sm font-semibold text-slate-900">{event.title}</p>
              <p class="mt-1 text-xs font-medium text-amber-700">{event.start} - {event.end}</p>
              {#if event.description}
                <p class="mt-2 text-sm text-slate-600">{event.description}</p>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="mt-3 text-sm text-slate-500">현재 등록된 현장 이벤트 시간이 없습니다.</p>
      {/if}
    </section>
  </section>
{/if}
