<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { Badge, Button } from '$lib/components/ui';
  import { coupangTravelApi } from '$lib/api/coupangTravel';
  import { isAbortError } from '$lib/utils/isAbortError.js';
  import type { MonitoringEvent } from '$lib/types';

  let monitoringEvents: MonitoringEvent[] = [];
  let loading = true;
  let error: string | null = null;

  let page = 1;
  let pageSize = 30;
  let total = 0;
  let totalPages = 1;

  let filters = {
    status: '',
    date_from: getTodayDate(),
    date_to: ''
  };

  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let abortController: AbortController | null = null;

  function getTodayDate(): string {
    return new Date().toISOString().split('T')[0];
  }

  function stopPolling(): void {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function abortInFlightRequest(): void {
    abortController?.abort();
    abortController = null;
  }

  function startPolling(): void {
    stopPolling();
    pollTimer = setInterval(() => {
      void fetchData(false);
    }, 5000);
  }

  async function fetchData(showLoading = true): Promise<void> {
    if (showLoading) loading = true;
    abortInFlightRequest();
    abortController = new AbortController();

    try {
      const eventsData = await coupangTravelApi.listEvents(
        {
          status: filters.status || undefined,
          date_from: filters.date_from || undefined,
          date_to: filters.date_to || undefined,
          page,
          page_size: pageSize
        },
        { signal: abortController.signal }
      );
      monitoringEvents = eventsData.items;
      total = eventsData.total;
      totalPages = eventsData.total_pages;
      error = null;
    } catch (e: unknown) {
      if (isAbortError(e)) {
        return;
      }
      error = e instanceof Error ? e.message : '쿠팡 모니터링 이력 로드 실패';
    } finally {
      if (showLoading) loading = false;
    }
  }

  function handleSearch(): void {
    page = 1;
    void fetchData(true);
  }

  function clearFilters(): void {
    filters = {
      status: '',
      date_from: getTodayDate(),
      date_to: ''
    };
    page = 1;
    void fetchData(true);
  }

  function getStatusBadgeVariant(status: string): 'success' | 'info' | 'secondary' | 'error' {
    if (status === 'success') return 'success';
    if (status === 'available') return 'info';
    if (status === 'error') return 'error';
    return 'secondary';
  }

  function getStatusLabel(status: string): string {
    const labels: Record<string, string> = {
      success: '성공',
      available: '예약 가능',
      no_slots: '매진',
      error: '오류'
    };
    return labels[status] || status;
  }

  function formatDateTime(dateStr: string | null): string {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('ko-KR');
  }

  function parseSlotsInfo(event: MonitoringEvent): Array<{ vendorItemName?: string; saleStatus?: string; stockCount?: number }> {
    if (!Array.isArray(event.slots_info)) {
      return [];
    }
    return event.slots_info
      .filter((item) => typeof item === 'object' && item !== null)
      .map((item) => item as { vendorItemName?: string; saleStatus?: string; stockCount?: number });
  }

  onMount(() => {
    void fetchData(true);
    startPolling();
  });

  onDestroy(() => {
    stopPolling();
    abortInFlightRequest();
  });
</script>

<div>
  <div class="card mb-6">
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div>
        <label for="history-status" class="block text-sm font-medium text-foreground mb-1">상태</label>
        <select id="history-status" class="input" bind:value={filters.status}>
          <option value="">전체</option>
          <option value="success">성공</option>
          <option value="available">예약 가능</option>
          <option value="no_slots">매진</option>
          <option value="error">오류</option>
        </select>
      </div>
      <div>
        <label for="history-date-from" class="block text-sm font-medium text-foreground mb-1">시작일</label>
        <input id="history-date-from" type="date" class="input" bind:value={filters.date_from} />
      </div>
      <div>
        <label for="history-date-to" class="block text-sm font-medium text-foreground mb-1">종료일</label>
        <input id="history-date-to" type="date" class="input" bind:value={filters.date_to} />
      </div>
      <div class="flex items-end gap-2">
        <Button variant="primary" onclick={handleSearch}>검색</Button>
        <Button variant="secondary" onclick={clearFilters}>초기화</Button>
      </div>
    </div>
  </div>

  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
  {:else if monitoringEvents.length === 0}
    <div class="card text-center py-12">
      <p class="text-muted-foreground">조회된 쿠팡 모니터링 이력이 없습니다.</p>
    </div>
  {:else}
    <div class="card">
      <div class="mb-4 text-sm text-muted-foreground">
        총 {total}건 중 {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)}
      </div>
      <div class="overflow-x-auto">
        <table class="table">
          <thead>
            <tr>
              <th>시각</th>
              <th>상품</th>
              <th>날짜</th>
              <th>상태</th>
              <th>슬롯 정보</th>
            </tr>
          </thead>
          <tbody>
            {#each monitoringEvents as event (event.id)}
              {@const slots = parseSlotsInfo(event)}
              <tr>
                <td class="text-sm text-muted-foreground whitespace-nowrap">{formatDateTime(event.timestamp)}</td>
                <td>
                  <div class="font-medium text-sm">{event.biz_item_name || '-'}</div>
                  <div class="text-xs text-muted-foreground">{event.business_name || '-'}</div>
                </td>
                <td class="text-sm">{event.schedule_date || '-'}</td>
                <td>
                  <Badge variant={getStatusBadgeVariant(event.status)}>
                    {getStatusLabel(event.status)}
                  </Badge>
                </td>
                <td class="text-xs text-muted-foreground">
                  {#if slots.length === 0}
                    -
                  {:else}
                    <div class="space-y-1">
                      {#each slots as slot}
                        <div>
                          {slot.vendorItemName || '-'} / {slot.saleStatus || '-'} / 재고 {slot.stockCount ?? 0}
                        </div>
                      {/each}
                    </div>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      {#if totalPages > 1}
        <div class="mt-4 flex items-center justify-between">
          <div class="text-sm text-muted-foreground">{page} / {totalPages}</div>
          <div class="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={page === 1}
              onclick={() => {
                page--;
                void fetchData(true);
              }}
            >
              이전
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={page === totalPages}
              onclick={() => {
                page++;
                void fetchData(true);
              }}
            >
              다음
            </Button>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
