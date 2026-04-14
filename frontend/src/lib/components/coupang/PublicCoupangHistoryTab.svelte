<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { coupangTravelApi, type CancellationStatsResponse } from '$lib/api/coupangTravel';
  import type { MonitoringEvent } from '$lib/types';
  import { isAbortError } from '$lib/utils/isAbortError.js';
  import { createPagePagination } from '$lib/utils/pagination.svelte';
  import PublicCoupangHistoryCard from '$lib/components/coupang/PublicCoupangHistoryCard.svelte';
  import PublicCoupangHistoryTable from '$lib/components/coupang/PublicCoupangHistoryTable.svelte';

  let loading = $state(true);
  let error = $state('');
  let stats = $state<CancellationStatsResponse>({ items: [], summary: { total: 0, avg_per_day: 0, peak_hour: null } });
  let events = $state<MonitoringEvent[]>([]);
  let selectedHours = $state<number[]>([]);
  let dateFrom = $state(getDefaultDateFrom());
  let dateTo = $state('');

  const pager = createPagePagination(20);
  let abortController: AbortController | null = null;

  function getDefaultDateFrom(): string {
    const d = new Date();
    d.setDate(d.getDate() - 365);
    return d.toISOString().split('T')[0];
  }

  function abortInFlightRequest(): void {
    abortController?.abort();
    abortController = null;
  }

  function getHoursParam(): string | undefined {
    return selectedHours.length > 0 ? selectedHours.join(',') : undefined;
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

  function formatHour(hour: number | null | undefined): string {
    return hour == null ? '-' : `${hour}시`;
  }

  async function loadEvents(): Promise<void> {
    const hoursParam = getHoursParam();
    const result = await coupangTravelApi.listEvents({
      status: 'available',
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      hours: hoursParam,
      page: pager.page,
      page_size: pager.pageSize
    }, abortController ? { signal: abortController.signal } : undefined);
    events = result.items;
    pager.total = result.total;
  }

  async function loadStats(): Promise<void> {
    const hoursParam = getHoursParam();
    stats = await coupangTravelApi.getCancellationStats({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      hours: hoursParam,
      group_by: 'day'
    }, abortController ? { signal: abortController.signal } : undefined);
  }

  async function loadAll(): Promise<void> {
    loading = true;
    error = '';
    pager.reset();
    abortInFlightRequest();
    abortController = new AbortController();

    try {
      await Promise.all([loadStats(), loadEvents()]);
    } catch (e: unknown) {
      if (!isAbortError(e)) {
        error = e instanceof Error ? e.message : '취소이력 로드 실패';
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
      await loadEvents();
    } catch (e: unknown) {
      if (!isAbortError(e)) {
        error = e instanceof Error ? e.message : '이력 페이지 로드 실패';
      }
    } finally {
      loading = false;
    }
  }

  function reset(): void {
    selectedHours = [];
    dateFrom = getDefaultDateFrom();
    dateTo = '';
    void loadAll();
  }

  function toggleHour(hour: number): void {
    selectedHours = selectedHours.includes(hour)
      ? selectedHours.filter((value) => value !== hour)
      : [...selectedHours, hour];
  }

  function isSelectedHour(hour: number): boolean {
    return selectedHours.includes(hour);
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
        <p class="text-sm text-muted-foreground">공개 페이지에서 감지된 취소표 이력을 모바일 기준으로 확인한다.</p>
        {#if events.length > 0}
          <p class="text-xs text-muted-foreground">최근 감지 {formatShortDateTime(events[0]?.timestamp ?? null)}</p>
        {/if}
      </div>
      <button class="btn btn-secondary btn-sm self-start" onclick={() => void loadAll()} disabled={loading}>
        새로고침
      </button>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-foreground">{stats.summary.total.toLocaleString()}</div>
        <div class="mt-1 text-xs text-muted-foreground">총 감지 횟수</div>
      </div>
      <div class="card py-4 text-center">
        <div class="text-3xl font-bold text-warning">{formatHour(stats.summary.peak_hour)}</div>
        <div class="mt-1 text-xs text-muted-foreground">피크 시간</div>
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
      <div class="text-xs font-medium text-muted-foreground">시간 단위 필터</div>
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded-full border px-2.5 py-1 text-xs font-medium transition
            {selectedHours.length === 0
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground'}"
          onclick={() => { selectedHours = []; }}
          disabled={loading}
        >
          전체
        </button>
        {#each Array.from({ length: 24 }, (_, hour) => hour) as hour}
          <button
            class="rounded-full border px-2.5 py-1 text-xs font-medium transition
              {isSelectedHour(hour)
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground'}"
            onclick={() => toggleHour(hour)}
            disabled={loading}
          >
            {hour}시
          </button>
        {/each}
      </div>
    </div>
  </section>

  {#if error}
    <div class="rounded bg-error-light px-4 py-3 text-sm text-error" role="alert">{error}</div>
  {/if}

  {#if loading}
    <div class="flex h-40 items-center justify-center">
      <div class="h-10 w-10 animate-spin rounded-full border-b-2 border-primary"></div>
    </div>
  {:else if events.length === 0}
    <div class="card py-10 text-center text-sm text-muted-foreground">
      조건에 맞는 취소이력이 없습니다.
    </div>
  {:else}
    <section class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-foreground">
          감지 이력
          {#if pager.total > 0}
            <span class="ml-1 font-normal text-muted-foreground">({pager.total.toLocaleString()}건)</span>
          {/if}
        </h3>
      </div>

      <PublicCoupangHistoryCard {events} />
      <PublicCoupangHistoryTable {events} />

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
