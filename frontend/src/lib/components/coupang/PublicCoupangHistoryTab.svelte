<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { coupangTravelApi } from '$lib/api/coupangTravel';
  import type { CoupangPublicHistoryResponse } from '$lib/types';
  import { isAbortError } from '$lib/utils/isAbortError.js';
  import { formatDuration } from '$lib/utils/coupangHistoryDisplay';
  import { createPagePagination } from '$lib/utils/pagination.svelte';
  import PublicCoupangHistoryCard from '$lib/components/coupang/PublicCoupangHistoryCard.svelte';
  import PublicCoupangHistoryTable from '$lib/components/coupang/PublicCoupangHistoryTable.svelte';

  let loading = $state(true);
  let error = $state('');
  let response = $state<CoupangPublicHistoryResponse>({
    items: [],
    summary: {
      total: 0,
      closed_pair_count: 0,
      open_pair_count: 0,
      avg_closed_duration_seconds: null
    },
    slot_time_options: [],
    total: 0,
    page: 1,
    page_size: 20,
    total_pages: 0
  });

  const pager = createPagePagination(20);
  let abortController: AbortController | null = null;

  function getDefaultDateFrom(): string {
    const d = new Date();
    d.setDate(d.getDate() - 365);
    return d.toISOString().split('T')[0];
  }

  let dateFrom = $state(getDefaultDateFrom());
  let dateTo = $state('');
  let selectedSlotTimes = $state<string[]>([]);

  const items = $derived(response.items);
  const summary = $derived(response.summary);
  const slotTimeOptions = $derived(response.slot_time_options);
  const visibleSlotTimes = $derived.by(() => {
    const seen = new Set<string>();
    return [...slotTimeOptions, ...selectedSlotTimes].filter((slotTime) => {
      if (!slotTime || seen.has(slotTime)) return false;
      seen.add(slotTime);
      return true;
    });
  });

  function abortInFlightRequest(): void {
    abortController?.abort();
    abortController = null;
  }

  function getSlotTimesParam(): string | undefined {
    return selectedSlotTimes.length > 0 ? selectedSlotTimes.join(',') : undefined;
  }

  function formatPageLabel(): string {
    if (pager.total === 0) return '0건';
    return `${pager.total.toLocaleString()}건`;
  }

  async function loadHistory(): Promise<void> {
    const result = await coupangTravelApi.getPublicHistoryPairs(
      {
        schedule_date_from: dateFrom || undefined,
        schedule_date_to: dateTo || undefined,
        slot_times: getSlotTimesParam(),
        page: pager.page,
        page_size: pager.pageSize
      },
      abortController ? { signal: abortController.signal } : undefined
    );
    response = result;
    pager.total = result.total;
  }

  async function loadAll(): Promise<void> {
    loading = true;
    error = '';
    pager.reset();
    abortInFlightRequest();
    abortController = new AbortController();

    try {
      await loadHistory();
    } catch (e: unknown) {
      if (!isAbortError(e)) {
        error = e instanceof Error ? e.message : '공개 전환 이력 로드 실패';
      }
    } finally {
      loading = false;
    }
  }

  async function search(): Promise<void> {
    await loadAll();
  }

  async function goToPage(page: number): Promise<void> {
    pager.goTo(page);
    loading = true;
    error = '';
    abortInFlightRequest();
    abortController = new AbortController();

    try {
      await loadHistory();
    } catch (e: unknown) {
      if (!isAbortError(e)) {
        error = e instanceof Error ? e.message : '공개 이력 페이지 로드 실패';
      }
    } finally {
      loading = false;
    }
  }

  function reset(): void {
    selectedSlotTimes = [];
    dateFrom = getDefaultDateFrom();
    dateTo = '';
    void loadAll();
  }

  function toggleSlotTime(slotTime: string): void {
    selectedSlotTimes = selectedSlotTimes.includes(slotTime)
      ? selectedSlotTimes.filter((value) => value !== slotTime)
      : [...selectedSlotTimes, slotTime];
  }

  function isSelectedSlotTime(slotTime: string): boolean {
    return selectedSlotTimes.includes(slotTime);
  }

  onMount(() => {
    void loadAll();
  });

  onDestroy(() => {
    abortInFlightRequest();
  });
</script>

<div class="space-y-6">
  <section class="card space-y-4">
    <div class="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
      <div class="space-y-1">
        <h2 class="text-lg font-semibold text-foreground">쿠팡 취소표 이력</h2>
        <p class="text-sm text-muted-foreground">
          공개 페이지는 발견 시각 기준의 공개 이력을 보여준다. 같은 슬롯의 열림과 다시 매진은 각각 별도 row로 노출된다.
        </p>
      </div>
      <button class="btn btn-secondary btn-sm self-start" onclick={() => void loadAll()} disabled={loading}>
        새로고침
      </button>
    </div>

      <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-foreground">{summary.total.toLocaleString()}</div>
        <div class="mt-1 text-[10px] leading-tight text-muted-foreground md:text-xs">전체 이력</div>
      </div>
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-rose-600">{summary.closed_pair_count.toLocaleString()}</div>
        <div class="mt-1 text-[10px] leading-tight text-muted-foreground md:text-xs">다시 매진</div>
      </div>
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-sky-600">{summary.open_pair_count.toLocaleString()}</div>
        <div class="mt-1 text-[10px] leading-tight text-muted-foreground md:text-xs">현재 열림</div>
      </div>
      <div class="card py-4 text-center">
        <div class="text-2xl font-semibold text-foreground">{formatDuration(summary.avg_closed_duration_seconds)}</div>
        <div class="mt-1 text-[10px] leading-tight text-muted-foreground md:text-xs">평균 다시 매진 소요</div>
      </div>
    </div>

    <div class="grid gap-3 md:grid-cols-3">
      <div class="md:col-span-1">
        <label class="mb-1 block text-xs font-medium text-muted-foreground" for="date-from">시작일</label>
        <input id="date-from" type="date" class="input w-full" bind:value={dateFrom} />
      </div>
      <div class="md:col-span-1">
        <label class="mb-1 block text-xs font-medium text-muted-foreground" for="date-to">종료일</label>
        <input id="date-to" type="date" class="input w-full" bind:value={dateTo} />
      </div>
      <div class="flex items-end gap-2 md:col-span-1">
        <button class="btn btn-primary btn-sm" onclick={search} disabled={loading}>
          {loading ? '조회 중...' : '조회'}
        </button>
        <button class="btn btn-secondary btn-sm" onclick={reset} disabled={loading}>초기화</button>
      </div>
    </div>

    <div class="space-y-2">
      <div class="flex items-center justify-between gap-2">
        <div class="text-xs font-medium text-muted-foreground">옵션 시간 필터</div>
        <div class="text-[11px] text-muted-foreground">
          {selectedSlotTimes.length > 0 ? `${selectedSlotTimes.length}개 선택` : '전체'}
        </div>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded-full border px-2.5 py-1 text-xs font-medium transition
            {selectedSlotTimes.length === 0
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground'}"
          onclick={() => { selectedSlotTimes = []; }}
          disabled={loading}
        >
          전체
        </button>
        {#each visibleSlotTimes as slotTime (slotTime)}
          <button
            class="rounded-full border px-2.5 py-1 text-xs font-medium transition
              {isSelectedSlotTime(slotTime)
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground'}"
            onclick={() => toggleSlotTime(slotTime)}
            disabled={loading}
          >
            {slotTime}
          </button>
        {/each}
      </div>
      <p class="text-[11px] text-muted-foreground">
        당일 도래한 옵션은 공개 이력에서 제외된다.
      </p>
    </div>
  </section>

  {#if error}
    <div class="rounded bg-error-light px-4 py-3 text-sm text-error" role="alert">{error}</div>
  {/if}

  {#if loading}
    <div class="flex h-40 items-center justify-center">
      <div class="h-10 w-10 animate-spin rounded-full border-b-2 border-primary"></div>
    </div>
  {:else if items.length === 0}
    <div class="card py-10 text-center text-sm text-muted-foreground">
      조건에 맞는 공개 이력이 없습니다.
    </div>
  {:else}
    <section class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-foreground">
          빈자리 요약
          <span class="ml-1 font-normal text-muted-foreground">({formatPageLabel()})</span>
        </h3>
        <p class="text-xs text-muted-foreground">빈자리와 다시 매진을 발견 시각 기준으로 나눠 보여준다.</p>
      </div>

      <PublicCoupangHistoryCard {items} />
      <PublicCoupangHistoryTable {items} />

      {#if pager.totalPages > 1}
        <div class="mt-4 flex items-center justify-center gap-1">
          <button class="btn btn-secondary btn-sm" onclick={() => goToPage(pager.page - 1)} disabled={pager.page <= 1}>
            이전
          </button>
          {#each Array.from({ length: Math.min(pager.totalPages, 7) }, (_, i) => {
            const half = 3;
            let start = Math.max(1, pager.page - half);
            const end = Math.min(pager.totalPages, start + 6);
            start = Math.max(1, end - 6);
            return start + i;
          }) as p}
            <button class="btn btn-sm {pager.page === p ? 'btn-primary' : 'btn-secondary'}" onclick={() => goToPage(p)}>
              {p}
            </button>
          {/each}
          <button
            class="btn btn-secondary btn-sm"
            onclick={() => goToPage(pager.page + 1)}
            disabled={pager.page >= pager.totalPages}
          >
            다음
          </button>
        </div>
      {/if}
    </section>
  {/if}
</div>
