<script lang="ts">
  import { onMount } from 'svelte';
  import MegabeautyCancellationListCard from '$lib/components/coupang/MegabeautyCancellationListCard.svelte';
  import MegabeautyCancellationListTable from '$lib/components/coupang/MegabeautyCancellationListTable.svelte';
  import {
    coupangTravelApi,
    type CancellationStatsResponse,
    type CoupangStatusSummary
  } from '$lib/api/coupangTravel';
  import type { MonitoringEvent } from '$lib/types';
  import { formatKoreanDateTime, normalizeHistoryText } from '$lib/utils/coupangHistoryDisplay';
  import { isAbortError } from '$lib/utils/isAbortError.js';
  import { createPagePagination } from '$lib/utils/pagination.svelte';

  let loading = $state(true);
  let error = $state('');
  let stats = $state<CancellationStatsResponse>({ items: [], summary: { total: 0, avg_per_day: 0, peak_hour: null } });
  let events = $state<MonitoringEvent[]>([]);
  let status = $state<CoupangStatusSummary | null>(null);

  const pager = createPagePagination(20);

  function getDefaultDateFrom(): string {
    const d = new Date();
    d.setDate(d.getDate() - 365);
    return d.toISOString().split('T')[0];
  }

  let dateFrom = $state(getDefaultDateFrom());
  let dateTo = $state('');

  function formatHour(h: number | null | undefined): string {
    if (h == null) return '-';
    return `${h}시`;
  }

  const recentDetectedAt = $derived(events[0]?.timestamp ?? null);
  const lastCheckedAt = $derived(
    status?.worker_health.updated_at ?? status?.worker_health.last_event_at ?? null
  );
  const lastCheckedTone = $derived(status?.worker_health.updated_at ? 'text-sky-600' : 'text-amber-600');
  const pageLabel = normalizeHistoryText('2026 쿠팡 메가뷰티쇼') || '메가뷰티쇼';

  async function loadEvents(): Promise<void> {
    try {
      const result = await coupangTravelApi.listEvents({
        status: 'available',
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page: pager.page,
        page_size: pager.pageSize
      });
      events = result.items;
      pager.total = result.total;
    } catch (e: unknown) {
      if (isAbortError(e)) return;
      error = e instanceof Error ? e.message : '메가뷰티쇼 이력 로드 실패';
    }
  }

  async function loadStats(): Promise<void> {
    try {
      stats = await coupangTravelApi.getCancellationStats({
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        group_by: 'day'
      });
    } catch (e: unknown) {
      if (isAbortError(e)) return;
      error = e instanceof Error ? e.message : '메가뷰티쇼 요약 로드 실패';
    }
  }

  async function loadStatus(): Promise<void> {
    try {
      status = await coupangTravelApi.getStatus();
    } catch (e: unknown) {
      if (isAbortError(e)) return;
      status = null;
    }
  }

  async function loadAll(): Promise<void> {
    loading = true;
    error = '';
    status = null;
    pager.reset();
    await Promise.all([loadStats(), loadEvents(), loadStatus()]);
    loading = false;
  }

  async function search(): Promise<void> {
    await loadAll();
  }

  function reset(): void {
    dateFrom = getDefaultDateFrom();
    dateTo = '';
    void loadAll();
  }

  async function goToPage(page: number): Promise<void> {
    pager.goTo(page);
    loading = true;
    error = '';
    await loadEvents();
    loading = false;
  }

  onMount(() => {
    void loadAll();
  });
</script>

<div class="space-y-6">
  <section class="card space-y-4">
    <div class="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
      <div class="space-y-1">
        <h2 class="text-lg font-semibold text-foreground">쿠팡 메가뷰티쇼 취소이력</h2>
        <p class="text-sm text-muted-foreground">
          현재 노출 중인 공개 페이지와 관리자 탭은 같은 {pageLabel} 전용 화면을 사용한다.
        </p>
      </div>
      <button class="btn btn-secondary btn-sm self-start" onclick={() => void loadAll()} disabled={loading}>
        새로고침
      </button>
    </div>

    <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div class="card text-center py-4">
        <div class="text-3xl font-bold text-foreground">{stats.summary.total.toLocaleString()}</div>
        <div class="text-xs text-muted-foreground mt-1">총 감지 횟수</div>
      </div>
      <div class="card text-center py-4">
        <div class="text-3xl font-bold text-primary">
          {formatKoreanDateTime(recentDetectedAt, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
        </div>
        <div class="text-xs text-muted-foreground mt-1">최근 감지</div>
      </div>
      <div class="card text-center py-4">
        <div class="text-3xl font-bold {lastCheckedTone}">
          {formatKoreanDateTime(lastCheckedAt, { hour: '2-digit', minute: '2-digit' })}
        </div>
        <div class="text-xs text-muted-foreground mt-1">마지막 확인</div>
      </div>
      <div class="card text-center py-4">
        <div class="text-3xl font-bold text-warning">{formatHour(stats.summary.peak_hour)}</div>
        <div class="text-xs text-muted-foreground mt-1">피크 시간</div>
      </div>
    </div>

    <div class="grid gap-3 md:grid-cols-3">
      <div class="md:col-span-1">
        <label class="block text-xs font-medium text-muted-foreground mb-1" for="date-from">시작일</label>
        <input id="date-from" type="date" class="input w-full" bind:value={dateFrom} />
      </div>
      <div class="md:col-span-1">
        <label class="block text-xs font-medium text-muted-foreground mb-1" for="date-to">종료일</label>
        <input id="date-to" type="date" class="input w-full" bind:value={dateTo} />
      </div>
      <div class="flex items-end gap-2 md:col-span-1">
        <button class="btn btn-primary btn-sm" onclick={search} disabled={loading}>
          {loading ? '조회 중...' : '조회'}
        </button>
        <button class="btn btn-secondary btn-sm" onclick={reset} disabled={loading}>
          초기화
        </button>
      </div>
    </div>
  </section>

  {#if error}
    <div class="rounded bg-error-light px-4 py-3 text-error text-sm" role="alert">{error}</div>
  {/if}

  {#if loading}
    <div class="flex justify-center items-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
    </div>
  {:else if events.length === 0}
    <div class="card text-center py-10 text-sm text-muted-foreground">
      조건에 맞는 메가뷰티쇼 취소이력이 없습니다.
    </div>
  {:else}
    <section class="space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-foreground">
          감지 이력
          {#if pager.total > 0}
            <span class="text-muted-foreground font-normal ml-1">({pager.total.toLocaleString()}건)</span>
          {/if}
        </h3>
      </div>

      <MegabeautyCancellationListCard {events} />
      <MegabeautyCancellationListTable {events} />

      {#if pager.totalPages > 1}
        <div class="flex items-center justify-center gap-1 mt-4">
          <button
            class="btn btn-secondary btn-sm"
            onclick={() => goToPage(pager.page - 1)}
            disabled={pager.page <= 1}
          >
            이전
          </button>
          {#each Array.from({ length: Math.min(pager.totalPages, 7) }, (_, i) => {
            const half = 3;
            let start = Math.max(1, pager.page - half);
            const end = Math.min(pager.totalPages, start + 6);
            start = Math.max(1, end - 6);
            return start + i;
          }) as p}
            <button
              class="btn btn-sm {pager.page === p ? 'btn-primary' : 'btn-secondary'}"
              onclick={() => goToPage(p)}
            >
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
