<script lang="ts">
  import { browser } from '$app/environment';
  import { onMount } from 'svelte';
  import { toast } from '$lib/stores/toast';
  import type { ExpoBooth, ExpoDraftBooth, ExpoMapDocument } from '$lib/types';
  import {
    buildExpoDraftStorageKey,
    buildExpoExportPayload,
    copyExpoExportPayloadToClipboard
  } from '../utils/authorDraft';
  import { toNormalizedPoint } from '../utils/mapTransform';

  interface Props {
    existingBooths: ExpoBooth[];
    map: ExpoMapDocument['map'];
    onSaveDrafts?: (drafts: ExpoDraftBooth[]) => Promise<void> | void;
    onDraftsChange?: (drafts: ExpoDraftBooth[]) => void;
    saveButtonLabel?: string;
    slug: string;
    title: string;
  }

  interface AuthorDraftState {
    currentNumber: number;
    drafts: ExpoDraftBooth[];
    padLength: number;
    prefix: string;
    startNumber: number;
    step: number;
  }

  let {
    existingBooths,
    map,
    onSaveDrafts,
    onDraftsChange,
    saveButtonLabel = 'JSON 복사',
    slug,
    title
  }: Props = $props();

  let stageEl: HTMLDivElement | null = null;
  let prefix = $state('A-');
  let startNumber = $state(1);
  let currentNumber = $state(1);
  let padLength = $state(2);
  let step = $state(1);
  let drafts = $state<ExpoDraftBooth[]>([]);
  let history = $state<ExpoDraftBooth[][]>([]);
  let stateLoaded = $state(false);

  const storageKey = buildExpoDraftStorageKey(slug);

  function buildName() {
    return `${prefix}${String(currentNumber).padStart(Math.max(1, padLength), '0')}`;
  }

  function pushHistory(nextDrafts: ExpoDraftBooth[]) {
    history = [...history.slice(-49), nextDrafts];
  }

  function saveState() {
    if (!browser) {
      return;
    }

    const payload: AuthorDraftState = {
      prefix,
      startNumber,
      currentNumber,
      padLength,
      step,
      drafts
    };

    localStorage.setItem(storageKey, JSON.stringify(payload));
  }

  function loadState() {
    if (!browser) {
      return;
    }

    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      return;
    }

    try {
      const payload = JSON.parse(raw) as Partial<AuthorDraftState>;
      prefix = payload.prefix ?? prefix;
      startNumber = payload.startNumber ?? startNumber;
      currentNumber = payload.currentNumber ?? startNumber;
      padLength = payload.padLength ?? padLength;
      step = payload.step ?? step;
      drafts = payload.drafts ?? drafts;
    } catch {
      toast.warning('저장된 author draft를 읽지 못했습니다.');
    }
  }

  function hasDuplicate(name: string) {
    return existingBooths.some((booth) => booth.id === name || booth.name === name) ||
      drafts.some((draft) => draft.name === name);
  }

  function handleMapClick(event: MouseEvent) {
    if (!stageEl) {
      return;
    }

    const rect = stageEl.getBoundingClientRect();
    const nextName = buildName();
    if (hasDuplicate(nextName)) {
      toast.warning(`중복 부스명입니다: ${nextName}`);
      return;
    }

    const nextPoint = toNormalizedPoint(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
    pushHistory(drafts);
    drafts = [
      ...drafts,
      {
        name: nextName,
        pin: nextPoint,
        createdAt: new Date().toISOString()
      }
    ];
    currentNumber += step;
  }

  function handleUndo() {
    const previous = history.at(-1);
    if (!previous) {
      toast.warning('되돌릴 좌표가 없습니다.');
      return;
    }

    history = history.slice(0, -1);
    drafts = previous;
    currentNumber = Math.max(startNumber, currentNumber - step);
  }

  function clearDrafts() {
    pushHistory(drafts);
    drafts = [];
  }

  function resetNumber() {
    currentNumber = startNumber;
  }

  function removeDraft(name: string) {
    pushHistory(drafts);
    drafts = drafts.filter((draft) => draft.name !== name);
  }

  async function copyJson() {
    if (!browser || drafts.length === 0) {
      toast.warning('복사할 좌표 draft가 없습니다.');
      return;
    }

    try {
      await copyExpoExportPayloadToClipboard(buildExpoExportPayload(slug, drafts, title));
      toast.success(`${drafts.length}개 draft를 복사했습니다.`);
    } catch {
      toast.error('클립보드 복사에 실패했습니다.');
    }
  }

  async function handleSaveDrafts() {
    if (drafts.length === 0) {
      toast.warning('저장할 좌표 draft가 없습니다.');
      return;
    }

    if (onSaveDrafts) {
      await onSaveDrafts(drafts);
      return;
    }

    await copyJson();
  }

  onMount(() => {
    loadState();
    stateLoaded = true;
  });

  $effect(() => {
    if (!stateLoaded) {
      return;
    }

    saveState();
    onDraftsChange?.(drafts);
  });
</script>

<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
  <section class="rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
    <div class="mb-4">
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Author Map</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-900">지도를 클릭하면 좌표 draft가 추가됩니다</h2>
    </div>

    <div
      bind:this={stageEl}
      class="relative overflow-hidden rounded-[28px] border border-slate-200 bg-[linear-gradient(180deg,_#fffef8_0%,_#f4ede2_100%)]"
      style={`aspect-ratio: ${map.width} / ${map.height};`}
      onclick={handleMapClick}
    >
      <img
        src={map.imageSrc}
        alt={map.alt}
        class="pointer-events-none absolute inset-0 h-full w-full object-contain"
        decoding="async"
        draggable="false"
        loading="eager"
      />

      {#each existingBooths as booth}
        <div
          class="pointer-events-none absolute flex h-6 min-w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-slate-200 bg-slate-900 px-2 text-[10px] font-bold text-white"
          style={`left: ${booth.pin.xNorm * 100}%; top: ${booth.pin.yNorm * 100}%;`}
        >
          {booth.id}
        </div>
      {/each}

      {#each drafts as draft}
        <div
          class="pointer-events-none absolute flex h-8 min-w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-amber-200 bg-amber-400 px-2 text-[10px] font-bold text-slate-950 shadow"
          style={`left: ${draft.pin.xNorm * 100}%; top: ${draft.pin.yNorm * 100}%;`}
        >
          {draft.name}
        </div>
      {/each}
    </div>
  </section>

  <aside class="space-y-4 rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Sequencer</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-900">부스명 자동 증가 입력</h2>
    </div>

    <div class="grid gap-3 sm:grid-cols-2">
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Prefix</span>
        <input bind:value={prefix} class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white" />
      </label>
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Start Number</span>
        <input bind:value={startNumber} type="number" min="1" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white" />
      </label>
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Pad Length</span>
        <input bind:value={padLength} type="number" min="1" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white" />
      </label>
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Step</span>
        <input bind:value={step} type="number" min="1" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white" />
      </label>
    </div>

    <div class="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
      다음 생성 부스명: <span class="font-semibold text-slate-950">{buildName()}</span>
    </div>

    <div class="flex flex-wrap gap-2">
      <button type="button" class="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white" onclick={handleSaveDrafts}>
        {saveButtonLabel}
      </button>
      <button type="button" class="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700" onclick={handleUndo}>
        Undo
      </button>
      <button type="button" class="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700" onclick={resetNumber}>
        번호 재설정
      </button>
      <button type="button" class="rounded-full border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700" onclick={clearDrafts}>
        draft 전체 삭제
      </button>
    </div>

    <div class="space-y-2">
      <h3 class="text-sm font-semibold text-slate-900">Draft 목록</h3>
      {#if drafts.length === 0}
        <p class="rounded-2xl border border-dashed border-slate-300 px-4 py-4 text-sm text-slate-500">
          아직 draft가 없습니다. 지도를 클릭해 좌표를 찍으세요.
        </p>
      {:else}
        <ul class="space-y-2">
          {#each drafts as draft}
            <li class="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3 text-sm">
              <div>
                <p class="font-semibold text-slate-900">{draft.name}</p>
                <p class="text-slate-500">
                  x={draft.pin.xNorm.toFixed(4)}, y={draft.pin.yNorm.toFixed(4)}
                </p>
              </div>
              <button
                type="button"
                class="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700"
                onclick={() => removeDraft(draft.name)}
              >
                삭제
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </aside>
</div>
