<script lang="ts">
  import type { ExpoTimeSlot } from '$lib/types';

  interface Props {
    matchCount: number;
    searchQuery: string;
    selectedSlotId: string | null;
    slotOptions: ExpoTimeSlot[];
    onReset: () => void;
    onSearchChange: (value: string) => void;
    onSelectSlot: (slotId: string | null) => void;
  }

  let {
    matchCount,
    searchQuery,
    selectedSlotId,
    slotOptions,
    onReset,
    onSearchChange,
    onSelectSlot
  }: Props = $props();
</script>

<section class="rounded-[28px] border border-slate-200 bg-white/92 p-4 shadow-sm backdrop-blur">
  <div class="flex flex-col gap-4">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Booth Filter</p>
        <h2 class="mt-1 text-lg font-semibold text-slate-900">시간대와 부스명을 함께 필터링</h2>
      </div>
      <div class="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white">
        매칭 {matchCount}개
      </div>
    </div>

    <div class="flex flex-col gap-3 lg:flex-row lg:items-center">
      <label class="flex-1">
        <span class="mb-1 block text-xs font-medium text-slate-500">부스명 검색</span>
        <input
          value={searchQuery}
          type="search"
          placeholder="예: 로스터스, 밀크, 그라인더"
          class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-amber-500 focus:bg-white"
          oninput={(event) => onSearchChange((event.currentTarget as HTMLInputElement).value)}
        />
      </label>

      <button
        type="button"
        class="rounded-2xl border border-slate-300 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
        onclick={onReset}
      >
        필터 리셋
      </button>
    </div>

    <div class="flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded-full border px-3 py-2 text-sm font-medium transition"
        class:border-amber-600={selectedSlotId === null}
        class:bg-amber-50={selectedSlotId === null}
        class:text-amber-900={selectedSlotId === null}
        class:border-slate-200={selectedSlotId !== null}
        class:bg-white={selectedSlotId !== null}
        class:text-slate-700={selectedSlotId !== null}
        onclick={() => onSelectSlot(null)}
      >
        전체 시간
      </button>

      {#each slotOptions as slot}
        <button
          type="button"
          class="rounded-full border px-3 py-2 text-sm font-medium transition"
          class:border-amber-600={selectedSlotId === slot.id}
          class:bg-amber-50={selectedSlotId === slot.id}
          class:text-amber-900={selectedSlotId === slot.id}
          class:border-slate-200={selectedSlotId !== slot.id}
          class:bg-white={selectedSlotId !== slot.id}
          class:text-slate-700={selectedSlotId !== slot.id}
          onclick={() => onSelectSlot(slot.id)}
        >
          {slot.label}
        </button>
      {/each}
    </div>
  </div>
</section>
