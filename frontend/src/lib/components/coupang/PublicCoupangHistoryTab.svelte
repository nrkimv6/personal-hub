<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { coupangTravelApi } from '$lib/api/coupangTravel';
  import type { CoupangPublicHistoryResponse } from '$lib/types';
  import { isAbortError } from '$lib/utils/isAbortError.js';
  import { createPagePagination } from '$lib/utils/pagination.svelte';
  import PublicCoupangHistoryCard from '$lib/components/coupang/PublicCoupangHistoryCard.svelte';
  import PublicCoupangHistoryTable from '$lib/components/coupang/PublicCoupangHistoryTable.svelte';

  let loading = $state(true);
  let error = $state('');
  let response = $state<CoupangPublicHistoryResponse>({
    items: [],
    summary: {
      total: 0,
      cancellation_count: 0,
      sold_out_count: 0,
      sale_observed_count: 0,
      open_count: 0,
      avg_observed_sale_seconds: null,
      last_transition_at: null
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

  function formatShortDateTime(value: string | null): string {
    if (!value) return '-';
    const date = new Date(value);
    return date.toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function formatDuration(seconds: number | null | undefined): string {
    if (seconds == null || Number.isNaN(seconds)) return '-';
    const rounded = Math.max(0, Math.round(seconds));
    if (rounded < 60) return `약 ${rounded}초`;
    const minutes = Math.floor(rounded / 60);
    const rest = rounded % 60;
    return rest > 0 ? `약 ${minutes}분 ${rest}초` : `약 ${minutes}분`;
  }

  function formatPageLabel(): string {
    if (pager.total === 0) return '0건';
    return `${pager.total.toLocaleString()}건`;
  }

  async function loadHistory(): Promise<void> {
    const result = await coupangTravelApi.getPublicHistoryTransitions(
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
          공개 페이지는 옵션 날짜+시간 기준 전환 이력만 보여준다. 판매 소요시간은 폴링 기반 관측치다.
        </p>
        {#if summary.last_transition_at}
          <p class="text-xs text-muted-foreground">최근 전환 {formatShortDateTime(summary.last_transition_at)}</p>
        {/if}
      </div>
      <button class="btn btn-secondary btn-sm self-start" onclick={() => void loadAll()} disabled={loading}>
        새로고침
      </button>
    </div>

    <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-foreground">{summary.total.toLocaleString()}</div>
        <div class="mt-1 text-xs text-muted-foreground">총 전환</div>
      </div>
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-emerald-600">{summary.cancellation_count.toLocaleString()}</div>
        <div class="mt-1 text-xs text-muted-foreground">취소표발생</div>
      </div>
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-rose-600">{summary.sold_out_count.toLocaleString()}</div>
        <div class="mt-1 text-xs text-muted-foreground">다시 매진</div>
      </div>
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-sky-600">{formatDuration(summary.avg_observed_sale_seconds)}</div>
        <div class="mt-1 text-xs text-muted-foreground">평균 판매 관측</div>
        <div class="mt-1 text-[11px] text-muted-foreground">잔여석 {summary.open_count.toLocaleString()}건</div>
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
      조건에 맞는 공개 전환 이력이 없습니다.
    </div>
  {:else}
    <section class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-foreground">
          전환 이력
          <span class="ml-1 font-normal text-muted-foreground">({formatPageLabel()})</span>
        </h3>
        <p class="text-xs text-muted-foreground">
          목록은 날짜+시간 기준이며, 판매 시간은 관측치다.
        </p>
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
