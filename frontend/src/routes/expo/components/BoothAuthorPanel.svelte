<script lang="ts">
  import { browser } from '$app/environment';
  import { onMount } from 'svelte';
  import { toast } from '$lib/stores/toast';
  import type { ExpoAllocationMode, ExpoBooth, ExpoDraftBooth, ExpoMapDocument, ExpoMapPin } from '$lib/types';
  import {
    buildExpoDraftStorageKey,
    buildExpoExportPayload,
    copyExpoExportPayloadToClipboard,
    loadAllocationMode,
    saveAllocationMode,
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

  /** 충돌 상태: strict 모드에서 클릭 시 충돌 발생 정보 */
  interface CollisionState {
    name: string;
    /** 충돌 대상이 정적 booth(existingBooths)인지 draft인지 */
    inExistingBooth: boolean;
    inDraft: boolean;
    /** 충돌한 정적 booth 이름 (inExistingBooth=true 일 때) */
    existingBoothName?: string;
    /** 클릭 좌표 (건너뛰기/덮어쓰기 시 재사용) */
    pendingPin: ExpoMapPin;
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

  /** 현재 allocation mode. 기본값: strict */
  let allocationMode = $state<ExpoAllocationMode>('strict');

  /** strict 모드 충돌 상태. null이면 충돌 없음 */
  let collisionState = $state<CollisionState | null>(null);

  /** 마지막으로 건너뛴 번호 목록 (skip 모드 피드백용) */
  let lastSkippedNames = $state<string[]>([]);

  const storageKey = buildExpoDraftStorageKey(slug);

  function buildNameFromNumber(num: number) {
    return `${prefix}${String(num).padStart(Math.max(1, padLength), '0')}`;
  }

  function buildName() {
    return buildNameFromNumber(currentNumber);
  }

  function hasDuplicateInExisting(name: string) {
    return existingBooths.some((booth) => booth.id === name || booth.name === name);
  }

  function hasDuplicateInDrafts(name: string) {
    return drafts.some((draft) => draft.name === name);
  }

  function hasDuplicate(name: string) {
    return hasDuplicateInExisting(name) || hasDuplicateInDrafts(name);
  }

  /** skip 모드: 현재 번호부터 시작해 충돌이 없는 다음 번호를 찾는다 (최대 1000 탐색) */
  function findNextFreeNumber(fromNumber: number): { number: number; skipped: string[] } {
    const skipped: string[] = [];
    let candidate = fromNumber;
    for (let i = 0; i < 1000; i++) {
      const name = buildNameFromNumber(candidate);
      if (!hasDuplicate(name)) {
        return { number: candidate, skipped };
      }
      skipped.push(name);
      candidate += step;
    }
    return { number: candidate, skipped };
  }

  /** overwrite 모드: 동일 이름의 draft 좌표를 교체한다. draft에 없으면 기존 booth override draft를 추가 */
  function applyOverwrite(name: string, pin: ExpoMapPin) {
    const draftIdx = drafts.findIndex((d) => d.name === name);
    if (draftIdx >= 0) {
      // 기존 draft 좌표 교체
      const prev = drafts[draftIdx];
      pushHistory(drafts);
      drafts = drafts.map((d, idx) =>
        idx === draftIdx
          ? {
              ...d,
              pin,
              updatedAt: new Date().toISOString(),
              source: 'overwrite' as const,
              overwrittenFrom: prev.pin,
            }
          : d
      );
    } else {
      // 정적 booth override: 동일 이름 draft 추가
      pushHistory(drafts);
      drafts = [
        ...drafts,
        {
          name,
          pin,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          source: 'overwrite' as const,
        },
      ];
    }
  }

  /** skip 모드에서 다음 번호 강조 텍스트 */
  const nextCandidateDisplay = $derived.by(() => {
    if (allocationMode === 'skip') {
      const { number } = findNextFreeNumber(currentNumber);
      return buildNameFromNumber(number);
    }
    return buildName();
  });

  function pushHistory(nextDrafts: ExpoDraftBooth[]) {
    history = [...history.slice(-49), nextDrafts];
  }

  function saveState() {
    if (!browser) return;
    const payload: AuthorDraftState = {
      prefix,
      startNumber,
      currentNumber,
      padLength,
      step,
      drafts,
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  }

  function loadState() {
    if (!browser) return;
    const raw = localStorage.getItem(storageKey);
    if (!raw) return;
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
    allocationMode = loadAllocationMode(slug);
  }

  function handleMapClick(event: MouseEvent) {
    if (!stageEl) return;
    collisionState = null;
    lastSkippedNames = [];

    const rect = stageEl.getBoundingClientRect();
    const pin = toNormalizedPoint(
      event.clientX - rect.left,
      event.clientY - rect.top,
      rect.width,
      rect.height
    );
    const candidateName = buildName();

    if (allocationMode === 'strict') {
      if (hasDuplicate(candidateName)) {
        // 충돌 상태 설정 — draft 추가 없음
        collisionState = {
          name: candidateName,
          inExistingBooth: hasDuplicateInExisting(candidateName),
          inDraft: hasDuplicateInDrafts(candidateName),
          existingBoothName: existingBooths.find(
            (b) => b.id === candidateName || b.name === candidateName
          )?.name,
          pendingPin: pin,
        };
        return;
      }
      pushHistory(drafts);
      drafts = [
        ...drafts,
        { name: candidateName, pin, createdAt: new Date().toISOString(), source: 'draft' },
      ];
      currentNumber += step;
    } else if (allocationMode === 'skip') {
      const { number, skipped } = findNextFreeNumber(currentNumber);
      const freeName = buildNameFromNumber(number);
      lastSkippedNames = skipped;
      pushHistory(drafts);
      drafts = [
        ...drafts,
        { name: freeName, pin, createdAt: new Date().toISOString(), source: 'draft' },
      ];
      currentNumber = number + step;
      if (skipped.length > 0) {
        toast.info(`건너뜀: ${skipped.join(', ')} → ${freeName} 추가`);
      }
    } else if (allocationMode === 'overwrite') {
      applyOverwrite(candidateName, pin);
      currentNumber += step;
    }
  }

  /** collision 블록의 "건너뛰기" 액션: strict에서 충돌 발생 후 사용자가 선택 */
  function handleCollisionSkip() {
    if (!collisionState) return;
    const collidedName = collisionState.name;
    const { number, skipped } = findNextFreeNumber(currentNumber + step);
    const freeName = buildNameFromNumber(number);
    pushHistory(drafts);
    drafts = [
      ...drafts,
      {
        name: freeName,
        pin: collisionState.pendingPin,
        createdAt: new Date().toISOString(),
        source: 'draft',
      },
    ];
    currentNumber = number + step;
    collisionState = null;
    if (skipped.length > 0) {
      toast.info(`건너뜀: ${[collidedName, ...skipped].filter(Boolean).join(', ')} → ${freeName}`);
    }
  }

  /** collision 블록의 "덮어쓰기" 액션 */
  function handleCollisionOverwrite() {
    if (!collisionState) return;
    applyOverwrite(collisionState.name, collisionState.pendingPin);
    currentNumber += step;
    collisionState = null;
  }

  /** collision 블록의 "취소" 액션 */
  function handleCollisionCancel() {
    collisionState = null;
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
    collisionState = null;
  }

  function clearDrafts() {
    pushHistory(drafts);
    drafts = [];
    collisionState = null;
  }

  function resetNumber() {
    currentNumber = startNumber;
    collisionState = null;
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

  function handleModeChange(mode: ExpoAllocationMode) {
    allocationMode = mode;
    collisionState = null;
    lastSkippedNames = [];
    saveAllocationMode(slug, mode);
  }

  onMount(() => {
    loadState();
    stateLoaded = true;
  });

  $effect(() => {
    if (!stateLoaded) return;
    saveState();
    onDraftsChange?.(drafts);
  });

  const modeLabel: Record<ExpoAllocationMode, string> = {
    strict: '엄격',
    skip: '건너뛰기',
    overwrite: '덮어쓰기',
  };

  const modeDescription: Record<ExpoAllocationMode, string> = {
    strict: '충돌 시 멈추고 확인 요청',
    skip: '충돌 시 다음 빈 번호로 자동 이동',
    overwrite: '충돌 시 기존 부스 좌표를 교체',
  };
</script>

<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
  <!-- 지도 영역 -->
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
      role="button"
      tabindex="0"
      aria-label="부스 좌표 클릭 영역"
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
          class="pointer-events-none absolute flex h-8 min-w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border px-2 text-[10px] font-bold shadow"
          class:border-amber-200={draft.source !== 'overwrite'}
          class:bg-amber-400={draft.source !== 'overwrite'}
          class:text-slate-950={draft.source !== 'overwrite'}
          class:border-rose-200={draft.source === 'overwrite'}
          class:bg-rose-400={draft.source === 'overwrite'}
          class:text-white={draft.source === 'overwrite'}
          style={`left: ${draft.pin.xNorm * 100}%; top: ${draft.pin.yNorm * 100}%;`}
        >
          {draft.name}
        </div>
      {/each}
    </div>
  </section>

  <!-- 사이드바 -->
  <aside class="space-y-4 rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
    <!-- Sequencer 헤더 -->
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Sequencer</p>
      <h2 class="mt-2 text-xl font-semibold text-slate-900">부스명 자동 증가 입력</h2>
    </div>

    <!-- 다음 생성 부스명 강조 카드 -->
    <div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
      <p class="text-xs font-semibold text-amber-700">다음 생성 부스명</p>
      <p class="mt-1 text-2xl font-bold tracking-tight text-amber-900">{nextCandidateDisplay}</p>
      <span class="mt-1 inline-block rounded-full bg-amber-200 px-2 py-0.5 text-xs font-semibold text-amber-900">
        {modeLabel[allocationMode]}
      </span>
    </div>

    <!-- Allocation Mode 선택 -->
    <div>
      <p class="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Allocation Mode</p>
      <div class="flex gap-2">
        {#each (['strict', 'skip', 'overwrite'] as ExpoAllocationMode[]) as mode}
          <button
            type="button"
            class="flex-1 rounded-2xl border px-3 py-2 text-xs font-semibold transition"
            class:border-amber-500={allocationMode === mode}
            class:bg-amber-50={allocationMode === mode}
            class:text-amber-900={allocationMode === mode}
            class:border-slate-200={allocationMode !== mode}
            class:bg-white={allocationMode !== mode}
            class:text-slate-600={allocationMode !== mode}
            class:border-rose-400={mode === 'overwrite' && allocationMode === mode}
            class:bg-rose-50={mode === 'overwrite' && allocationMode === mode}
            class:text-rose-900={mode === 'overwrite' && allocationMode === mode}
            onclick={() => handleModeChange(mode)}
            title={modeDescription[mode]}
          >
            {modeLabel[mode]}
          </button>
        {/each}
      </div>
      <p class="mt-1 text-xs text-slate-500">{modeDescription[allocationMode]}</p>
    </div>

    <!-- 충돌 경고 블록 (strict 모드) -->
    {#if collisionState}
      <div class="rounded-2xl border border-rose-300 bg-rose-50 px-4 py-4">
        <p class="text-sm font-semibold text-rose-800">
          중복: {collisionState.name}
          {#if collisionState.inExistingBooth}
            <span class="ml-1 text-xs font-normal text-rose-600">
              (기존 부스{collisionState.existingBoothName ? ` · ${collisionState.existingBoothName}` : ''})
            </span>
          {:else if collisionState.inDraft}
            <span class="ml-1 text-xs font-normal text-rose-600">(현재 draft)</span>
          {/if}
        </p>
        <p class="mt-1 text-xs text-rose-600">
          동일한 부스명이 이미 존재합니다. 아래 중 하나를 선택하세요.
        </p>
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-500"
            onclick={handleCollisionSkip}
          >
            건너뛰기
          </button>
          <button
            type="button"
            class="rounded-full border border-rose-400 bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-rose-700"
            onclick={handleCollisionOverwrite}
          >
            덮어쓰기 (좌표 교체)
          </button>
          <button
            type="button"
            class="rounded-full border border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-200"
            onclick={handleCollisionCancel}
          >
            취소
          </button>
        </div>
      </div>
    {/if}

    <!-- 시퀀서 설정 -->
    <div class="grid gap-3 sm:grid-cols-2">
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Prefix</span>
        <input
          bind:value={prefix}
          class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white"
          onchange={() => { collisionState = null; }}
        />
      </label>
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Start Number</span>
        <input
          bind:value={startNumber}
          type="number"
          min="1"
          class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white"
        />
      </label>
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Pad Length</span>
        <input
          bind:value={padLength}
          type="number"
          min="1"
          class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white"
        />
      </label>
      <label class="text-sm">
        <span class="mb-1 block font-medium text-slate-600">Step</span>
        <input
          bind:value={step}
          type="number"
          min="1"
          class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 outline-none focus:border-amber-500 focus:bg-white"
        />
      </label>
    </div>

    <!-- 액션 버튼 -->
    <div class="flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
        onclick={handleSaveDrafts}
      >
        {saveButtonLabel}
      </button>
      <button
        type="button"
        class="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
        onclick={handleUndo}
      >
        Undo
      </button>
      <button
        type="button"
        class="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
        onclick={resetNumber}
      >
        번호 재설정
      </button>
      <button
        type="button"
        class="rounded-full border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700"
        onclick={clearDrafts}
      >
        draft 전체 삭제
      </button>
    </div>

    <!-- Draft 목록 -->
    <div class="space-y-2">
      <h3 class="text-sm font-semibold text-slate-900">Draft 목록 ({drafts.length})</h3>
      {#if drafts.length === 0}
        <p class="rounded-2xl border border-dashed border-slate-300 px-4 py-4 text-sm text-slate-500">
          아직 draft가 없습니다. 지도를 클릭해 좌표를 찍으세요.
        </p>
      {:else}
        <ul class="space-y-2">
          {#each drafts as draft}
            <li
              class="flex items-center justify-between rounded-2xl px-4 py-3 text-sm"
              class:bg-amber-50={draft.source !== 'overwrite'}
              class:bg-rose-50={draft.source === 'overwrite'}
            >
              <div>
                <p class="font-semibold text-slate-900">
                  {draft.name}
                  {#if draft.source === 'overwrite'}
                    <span class="ml-1 rounded-full bg-rose-200 px-1.5 py-0.5 text-[10px] font-semibold text-rose-800">덮어쓰기</span>
                  {/if}
                </p>
                <p class="text-slate-500">
                  x={draft.pin.xNorm.toFixed(4)}, y={draft.pin.yNorm.toFixed(4)}
                </p>
                {#if draft.updatedAt}
                  <p class="text-xs text-slate-400">수정됨: {new Date(draft.updatedAt).toLocaleTimeString('ko-KR')}</p>
                {/if}
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
