<script lang="ts">
  import { onMount } from 'svelte';
  import CancellationListCard from '$lib/components/coupang/CancellationListCard.svelte';
  import CancellationListTable from '$lib/components/coupang/CancellationListTable.svelte';
  import {
    coupangTravelApi,
    type CancellationStatsResponse,
    type CancellationByProductResponse,
    type CoupangStatusSummary
  } from '$lib/api/coupangTravel';
  import type { MonitoringEvent } from '$lib/types';
  import { formatKoreanDateTime } from '$lib/utils/coupangHistoryDisplay';
  import { createPagePagination } from '$lib/utils/pagination.svelte';

  // ── 상태 ─────────────────────────────────────────────────────────────────────
  let loading = $state(true);
  let statsLoading = $state(false);
  let error = $state('');

  let stats = $state<CancellationStatsResponse>({ items: [], summary: { total: 0, avg_per_day: 0, peak_hour: null } });
  let hourlyStats = $state<CancellationStatsResponse>({ items: [], summary: { total: 0, avg_per_day: 0, peak_hour: null } });
  let products = $state<CancellationByProductResponse>({ items: [] });
  let events = $state<MonitoringEvent[]>([]);
  let status = $state<CoupangStatusSummary | null>(null);

  const pager = createPagePagination(20);

  // ── 필터 ─────────────────────────────────────────────────────────────────────
  function getDefaultDateFrom(): string {
    const d = new Date();
    d.setDate(d.getDate() - 6);
    return d.toISOString().split('T')[0];
  }

  let dateFrom = $state(getDefaultDateFrom());
  let dateTo = $state('');
  let selectedHours = $state<number[]>([]);
  let bizItemId = $state<number | null>(null);

  const hoursParam = $derived(selectedHours.length > 0 ? selectedHours.join(',') : undefined);
  const recentDetectedAt = $derived(events[0]?.timestamp ?? null);
  const summaryValueClass = 'text-lg font-bold leading-tight md:text-xl';
  const lastCheckedAt = $derived(
    status?.worker_health.status === 'healthy' ? (status?.worker_health.last_checked_at ?? null) : null
  );
  const lastCheckedTone = $derived(
    lastCheckedAt ? 'text-sky-600' : 'text-muted-foreground'
  );

  // ── 데이터 로드 ───────────────────────────────────────────────────────────────
  async function loadStats(): Promise<void> {
    statsLoading = true;
    try {
      const [statsData, hourlyData, productsData] = await Promise.all([
        coupangTravelApi.getCancellationStats({
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          biz_item_id: bizItemId ?? undefined,
          hours: hoursParam,
          group_by: 'day'
        }),
        coupangTravelApi.getCancellationStats({
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          biz_item_id: bizItemId ?? undefined,
          hours: hoursParam,
          group_by: 'hour'
        }),
        coupangTravelApi.getCancellationByProduct({
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          hours: hoursParam
        })
      ]);
      stats = statsData;
      hourlyStats = hourlyData;
      products = productsData;
    } catch (e) {
      error = e instanceof Error ? e.message : '통계 로드 실패';
    } finally {
      statsLoading = false;
    }
  }

  async function loadEvents(): Promise<void> {
    try {
      const result = await coupangTravelApi.listEvents({
        status: 'available',
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        biz_item_id: bizItemId ?? undefined,
        page: pager.page,
        page_size: pager.pageSize
      });
      events = result.items;
      pager.total = result.total;
    } catch (e) {
      error = e instanceof Error ? e.message : '이력 로드 실패';
    }
  }

  async function loadStatus(): Promise<void> {
    try {
      status = await coupangTravelApi.getStatus();
    } catch (e) {
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

  async function onSearch(): Promise<void> {
    await loadAll();
  }

  function onReset(): void {
    dateFrom = getDefaultDateFrom();
    dateTo = '';
    selectedHours = [];
    bizItemId = null;
    void loadAll();
  }

  function toggleHour(h: number): void {
    if (selectedHours.includes(h)) {
      selectedHours = selectedHours.filter((x) => x !== h);
    } else {
      selectedHours = [...selectedHours, h].sort((a, b) => a - b);
    }
  }

  async function goToPage(p: number): Promise<void> {
    pager.goTo(p);
    await loadEvents();
  }

  onMount(() => {
    void loadAll();
  });

  // ── 차트 헬퍼 ────────────────────────────────────────────────────────────────
  const CHART_H = 80;
  const CHART_BAR_W = 24;
  const CHART_GAP = 6;

  const chartItems = $derived(stats.items.slice(-14));
  const chartMax = $derived(Math.max(1, ...chartItems.map((i) => i.count)));

  function barHeight(count: number): number {
    return Math.max(2, Math.round((count / chartMax) * CHART_H));
  }

  function formatDayLabel(dateStr: string | null | undefined): string {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }

  // ── 피크 시간 포맷 ────────────────────────────────────────────────────────────
  function formatHour(h: number | null | undefined): string {
    if (h == null) return '-';
    return `${h}시`;
  }
</script>

<div class="space-y-6">
  <!-- 필터 패널 -->
  <section class="card space-y-4">
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1" for="date-from">시작일</label>
        <input
          id="date-from"
          type="date"
          class="input w-full"
          bind:value={dateFrom}
        />
      </div>
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1" for="date-to">종료일</label>
        <input
          id="date-to"
          type="date"
          class="input w-full"
          bind:value={dateTo}
        />
      </div>
      <div class="col-span-2 sm:col-span-2">
        <label class="block text-xs font-medium text-muted-foreground mb-1" for="product-select">상품</label>
        <select
          id="product-select"
          class="input w-full"
          onchange={(e) => {
            const val = (e.target as HTMLSelectElement).value;
            bizItemId = val ? Number(val) : null;
          }}
        >
          <option value="">전체 상품</option>
          {#each products.items as p (p.biz_item_id)}
            <option value={p.biz_item_id} selected={bizItemId === p.biz_item_id}>
              {p.biz_item_name}
            </option>
          {/each}
        </select>
      </div>
    </div>

    <!-- 시간 필터 칩 -->
    <div>
      <p class="text-xs font-medium text-muted-foreground mb-2">
        감지 시간대 (통계용, 복수 선택 가능 — OR 조건)
        {#if selectedHours.length > 0}
          <span class="ml-1 text-primary">{selectedHours.map(formatHour).join(', ')} 선택됨</span>
        {:else}
          <span class="ml-1 text-muted-foreground">전체</span>
        {/if}
      </p>
      <div class="flex flex-wrap gap-1">
        {#each Array.from({ length: 24 }, (_, i) => i) as h}
          <button
            type="button"
            class="px-2 py-0.5 text-xs rounded-full border transition-colors
              {selectedHours.includes(h)
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-card text-muted-foreground border-border hover:border-primary'}"
            onclick={() => toggleHour(h)}
          >
            {h}시
          </button>
        {/each}
      </div>
    </div>

    <div class="flex gap-2 pt-1">
      <button class="btn btn-primary btn-sm" onclick={onSearch} disabled={loading}>
        {loading ? '조회 중...' : '조회'}
      </button>
      <button class="btn btn-secondary btn-sm" onclick={onReset} disabled={loading}>
        초기화
      </button>
    </div>
  </section>

  {#if error}
    <div class="rounded bg-error-light px-4 py-3 text-error text-sm" role="alert">{error}</div>
  {/if}

  {#if loading}
    <div class="flex justify-center items-center h-40">
      <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
    </div>
  {:else}
    <!-- 요약 카드 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div class="card text-center py-4">
        <div class="text-3xl font-bold text-foreground">{stats.summary.total.toLocaleString()}</div>
        <div class="text-xs text-muted-foreground mt-1">총 감지 횟수</div>
      </div>
      <div class="card text-center py-4">
        <div class={`${summaryValueClass} font-bold text-primary`}>
          {formatKoreanDateTime(recentDetectedAt, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
        </div>
        <div class="text-xs text-muted-foreground mt-1">최근 감지</div>
      </div>
      <div class="card text-center py-4">
        <div class={`${summaryValueClass} font-bold ${lastCheckedTone}`}>
          {formatKoreanDateTime(lastCheckedAt, { hour: '2-digit', minute: '2-digit' })}
        </div>
        <div class="text-xs text-muted-foreground mt-1">마지막 확인</div>
      </div>
      <div class="card text-center py-4">
        <div class="text-3xl font-bold text-warning">{formatHour(stats.summary.peak_hour)}</div>
        <div class="text-xs text-muted-foreground mt-1">피크 시간</div>
      </div>
    </div>

    <!-- 일별 추이 차트 -->
    {#if chartItems.length > 0}
      <section class="card">
        <h2 class="text-sm font-semibold mb-3 text-foreground">일별 취소표 감지 추이</h2>
        <div class="overflow-x-auto">
          <svg
            width={chartItems.length * (CHART_BAR_W + CHART_GAP)}
            height={CHART_H + 28}
            role="img"
            aria-label="일별 취소표 감지 추이 차트"
          >
            {#each chartItems as item, i}
              {@const x = i * (CHART_BAR_W + CHART_GAP)}
              {@const bh = barHeight(item.count)}
              <g>
                <rect
                  x={x}
                  y={CHART_H - bh}
                  width={CHART_BAR_W}
                  height={bh}
                  class="fill-primary opacity-80"
                  rx="2"
                />
                {#if item.count > 0}
                  <text
                    x={x + CHART_BAR_W / 2}
                    y={CHART_H - bh - 3}
                    text-anchor="middle"
                    class="text-[9px] fill-muted-foreground"
                    font-size="9"
                  >{item.count}</text>
                {/if}
                <text
                  x={x + CHART_BAR_W / 2}
                  y={CHART_H + 14}
                  text-anchor="middle"
                  class="text-[9px] fill-muted-foreground"
                  font-size="9"
                >{formatDayLabel(item.date)}</text>
              </g>
            {/each}
          </svg>
        </div>
      </section>
    {/if}

    <!-- 시간대별 히트맵 -->
    {#if hourlyStats.items.length > 0}
      {@const maxHourCount = Math.max(1, ...hourlyStats.items.map((i) => i.count))}
      {@const hourMap = Object.fromEntries(hourlyStats.items.map((i) => [i.hour ?? -1, i.count]))}
      <section class="card">
        <h2 class="text-sm font-semibold mb-3 text-foreground">시간대별 감지 빈도</h2>
        <div class="flex flex-wrap gap-1">
          {#each Array.from({ length: 24 }, (_, h) => h) as h}
            {@const cnt = hourMap[h] ?? 0}
            {@const intensity = cnt === 0 ? 0 : Math.ceil((cnt / maxHourCount) * 5)}
            <div class="flex flex-col items-center gap-0.5">
              <div
                class="w-7 h-7 rounded text-center text-[9px] leading-7 font-medium transition-colors
                  {intensity === 0 ? 'bg-muted text-muted-foreground'
                  : intensity === 1 ? 'bg-orange-100 text-orange-700'
                  : intensity === 2 ? 'bg-orange-200 text-orange-800'
                  : intensity === 3 ? 'bg-orange-300 text-orange-900'
                  : intensity === 4 ? 'bg-orange-500 text-white'
                  : 'bg-orange-700 text-white'}"
                title="{h}시: {cnt}회"
              >{cnt > 0 ? cnt : ''}</div>
              <span class="text-[9px] text-muted-foreground">{h}</span>
            </div>
          {/each}
        </div>
        {#if stats.summary.peak_hour != null}
          <p class="text-xs text-muted-foreground mt-2">피크 시간: {stats.summary.peak_hour}시</p>
        {/if}
      </section>
    {/if}

    <!-- 상품별 통계 -->
    {#if products.items.length > 0}
      <section class="card">
        <h2 class="text-sm font-semibold mb-3 text-foreground">
          상품별 취소표 감지 현황
          <span class="text-muted-foreground font-normal ml-1">({products.items.length}개)</span>
        </h2>
        <div class="space-y-2">
          {#each products.items as p, i (p.biz_item_id)}
            {@const maxCount = products.items[0]?.total_count ?? 1}
            <div class="flex items-center gap-3">
              <span class="w-5 text-xs text-muted-foreground text-right shrink-0">{i + 1}</span>
              <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between mb-0.5">
                  <span class="text-sm font-medium truncate">{p.biz_item_name}</span>
                  <span class="text-sm font-bold text-primary ml-2 shrink-0">{p.total_count}회</span>
                </div>
                <div class="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    class="h-full rounded-full bg-primary transition-all"
                    style="width: {Math.round((p.total_count / maxCount) * 100)}%"
                  ></div>
                </div>
                {#if p.last_detected}
                  <p class="text-xs text-muted-foreground mt-0.5">
                    마지막 감지: {formatKoreanDateTime(p.last_detected, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    {#if p.avg_interval_hours != null}
                      &middot; 평균 {p.avg_interval_hours.toFixed(1)}h 간격
                    {/if}
                  </p>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <!-- 감지 이력 -->
    <section>
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-semibold text-foreground">
          감지 이력
          {#if pager.total > 0}
            <span class="text-muted-foreground font-normal ml-1">({pager.total.toLocaleString()}건)</span>
          {/if}
        </h2>
      </div>

      {#if events.length === 0}
        <div class="card text-center py-10 text-sm text-muted-foreground">
          조건에 맞는 취소표 감지 이력이 없습니다.
        </div>
      {:else}
        <CancellationListCard {events} />
        <CancellationListTable {events} />

        <!-- 페이지네이션 -->
        {#if pager.totalPages > 1}
          <div class="flex items-center justify-center gap-1 mt-4">
            <button
              class="btn btn-secondary btn-sm"
              onclick={() => goToPage(pager.page - 1)}
              disabled={pager.page <= 1}
            >이전</button>
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
              >{p}</button>
            {/each}
            <button
              class="btn btn-secondary btn-sm"
              onclick={() => goToPage(pager.page + 1)}
              disabled={pager.page >= pager.totalPages}
            >다음</button>
          </div>
        {/if}
      {/if}
    </section>
  {/if}
</div>
