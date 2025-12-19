<script lang="ts">
  import { slotApi } from '$lib/api';
  import type { SlotCheckResponse, DateSlots, SlotInfo } from '$lib/types';

  // 입력 상태
  let url = $state('');
  let advancedMode = $state(false);
  let businessId = $state('');
  let bizItemId = $state('');
  let targetDate = $state('');
  let daysAhead = $state(14);

  // 조회 상태
  let loading = $state(false);
  let error = $state<string | null>(null);
  let result = $state<SlotCheckResponse | null>(null);

  // 날짜별 접기/펼치기 상태
  let expandedDates = $state<Set<string>>(new Set());

  // 슬롯 조회
  async function checkSlots() {
    if (!url && !advancedMode) {
      error = 'URL을 입력해주세요';
      return;
    }
    if (advancedMode && (!businessId || !bizItemId)) {
      error = '업체 ID와 상품 ID를 모두 입력해주세요';
      return;
    }

    loading = true;
    error = null;
    result = null;

    try {
      if (advancedMode) {
        result = await slotApi.check({
          business_id: businessId,
          biz_item_id: bizItemId,
          target_date: targetDate || undefined,
          days_ahead: daysAhead
        });
      } else {
        result = await slotApi.check({
          url,
          target_date: targetDate || undefined,
          days_ahead: daysAhead
        });
      }
      // 첫 번째 날짜 자동 펼치기
      if (result?.slots_by_date?.length > 0) {
        expandedDates = new Set([result.slots_by_date[0].date]);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : '조회 실패';
    } finally {
      loading = false;
    }
  }

  // Enter 키로 조회
  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      checkSlots();
    }
  }

  // 날짜 접기/펼치기 토글
  function toggleDate(date: string) {
    const newSet = new Set(expandedDates);
    if (newSet.has(date)) {
      newSet.delete(date);
    } else {
      newSet.add(date);
    }
    expandedDates = newSet;
  }

  // 전체 펼치기/접기
  function expandAll() {
    if (result?.slots_by_date) {
      expandedDates = new Set(result.slots_by_date.map(d => d.date));
    }
  }

  function collapseAll() {
    expandedDates = new Set();
  }

  // 슬롯 상태에 따른 색상
  function getSlotBgColor(slot: SlotInfo): string {
    if (!slot.is_available) return 'bg-red-50';
    if (slot.remaining <= 2) return 'bg-yellow-50';
    return 'bg-green-50';
  }

  function getSlotTextColor(slot: SlotInfo): string {
    if (!slot.is_available) return 'text-red-600';
    if (slot.remaining <= 2) return 'text-yellow-600';
    return 'text-green-600';
  }

  function getSlotBorderColor(slot: SlotInfo): string {
    if (!slot.is_available) return 'border-red-200';
    if (slot.remaining <= 2) return 'border-yellow-200';
    return 'border-green-200';
  }

  // 진행률 계산
  function getProgress(booked: number, capacity: number): number {
    return capacity > 0 ? (booked / capacity) * 100 : 0;
  }

  // 진행률 바 색상
  function getProgressColor(booked: number, capacity: number): string {
    const ratio = capacity > 0 ? booked / capacity : 1;
    if (ratio >= 1) return 'bg-red-500';
    if (ratio >= 0.8) return 'bg-yellow-500';
    return 'bg-green-500';
  }

  // 날짜 요약 상태
  function getDateStatusColor(dateSlots: DateSlots): string {
    const { total_remaining, total_capacity } = dateSlots.summary;
    if (total_remaining === 0) return 'text-red-600';
    if (total_remaining / total_capacity < 0.2) return 'text-yellow-600';
    return 'text-green-600';
  }

  // URL 복사
  function copyUrl() {
    if (result) {
      const naverUrl = `https://booking.naver.com/booking/13/bizes/${result.business.business_id}/items/${result.biz_item.biz_item_id}`;
      navigator.clipboard.writeText(naverUrl);
    }
  }

  // 오늘 날짜 기본값
  function getTodayDate(): string {
    return new Date().toISOString().split('T')[0];
  }
</script>

<div class="p-6 max-w-6xl mx-auto">
  <!-- 헤더 -->
  <div class="mb-6">
    <h1 class="text-2xl font-bold text-gray-900">슬롯 조회</h1>
    <p class="text-gray-600 mt-1">네이버 예약 슬롯 현황을 실시간으로 조회합니다</p>
  </div>

  <!-- 입력 폼 -->
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
    {#if !advancedMode}
      <!-- URL 입력 -->
      <div class="flex gap-3">
        <input
          type="text"
          bind:value={url}
          onkeydown={handleKeydown}
          placeholder="네이버 예약 URL 입력 (예: https://booking.naver.com/booking/13/bizes/...)"
          class="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <button
          onclick={checkSlots}
          disabled={loading}
          class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
        >
          {#if loading}
            <span class="flex items-center gap-2">
              <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              조회 중
            </span>
          {:else}
            조회
          {/if}
        </button>
      </div>
    {:else}
      <!-- 고급 모드: ID 직접 입력 -->
      <div class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">업체 ID (business_id)</label>
          <input
            type="text"
            bind:value={businessId}
            placeholder="예: 1269828"
            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">상품 ID (biz_item_id)</label>
          <input
            type="text"
            bind:value={bizItemId}
            placeholder="예: 6309738"
            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      </div>
      <button
        onclick={checkSlots}
        disabled={loading}
        class="w-full px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
      >
        {#if loading}
          <span class="flex items-center justify-center gap-2">
            <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            조회 중
          </span>
        {:else}
          조회
        {/if}
      </button>
    {/if}

    <!-- 옵션 -->
    <div class="mt-4 pt-4 border-t border-gray-200">
      <div class="flex flex-wrap items-center gap-6">
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            bind:checked={advancedMode}
            class="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
          />
          <span class="text-sm text-gray-700">고급 모드 (ID 직접 입력)</span>
        </label>

        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-700">시작일:</label>
          <input
            type="date"
            bind:value={targetDate}
            min={getTodayDate()}
            class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        <div class="flex items-center gap-2">
          <label class="text-sm text-gray-700">조회 기간:</label>
          <select
            bind:value={daysAhead}
            class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          >
            <option value={7}>7일</option>
            <option value={14}>14일</option>
            <option value={21}>21일</option>
            <option value={28}>28일</option>
            <option value={35}>35일</option>
          </select>
        </div>
      </div>
    </div>
  </div>

  <!-- 에러 메시지 -->
  {#if error}
    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6">
      <div class="flex items-center gap-2">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{error}</span>
      </div>
    </div>
  {/if}

  <!-- 조회 결과 -->
  {#if result}
    <!-- 요약 정보 -->
    <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-6">
          <div>
            <span class="text-gray-500 text-sm">업체</span>
            <p class="font-semibold text-gray-900">{result.business.name}</p>
          </div>
          <div class="h-8 w-px bg-gray-200"></div>
          <div>
            <span class="text-gray-500 text-sm">상품</span>
            <p class="font-semibold text-gray-900">{result.biz_item.name}</p>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <div class="text-center px-4 py-2 bg-gray-50 rounded-lg">
            <p class="text-2xl font-bold text-gray-900">{result.summary.total_slots}</p>
            <p class="text-xs text-gray-500">총 슬롯</p>
          </div>
          <div class="text-center px-4 py-2 bg-green-50 rounded-lg">
            <p class="text-2xl font-bold text-green-600">{result.summary.total_available_slots}</p>
            <p class="text-xs text-gray-500">예약 가능</p>
          </div>
          <div class="text-center px-4 py-2 bg-blue-50 rounded-lg">
            <p class="text-2xl font-bold text-blue-600">{result.summary.available_dates.length}</p>
            <p class="text-xs text-gray-500">예약 가능일</p>
          </div>
        </div>
      </div>
      <div class="mt-4 pt-4 border-t border-gray-200 flex justify-between items-center">
        <span class="text-xs text-gray-400">
          조회 시각: {new Date(result.queried_at).toLocaleString('ko-KR')}
        </span>
        <div class="flex gap-2">
          <button
            onclick={copyUrl}
            class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            URL 복사
          </button>
          <button
            onclick={expandAll}
            class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            전체 펼치기
          </button>
          <button
            onclick={collapseAll}
            class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            전체 접기
          </button>
        </div>
      </div>
    </div>

    <!-- 날짜별 슬롯 -->
    <div class="space-y-3">
      {#each result.slots_by_date as dateSlots}
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <!-- 날짜 헤더 -->
          <button
            onclick={() => toggleDate(dateSlots.date)}
            class="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 transition-colors"
          >
            <div class="flex items-center gap-3">
              <svg
                class="w-5 h-5 text-gray-400 transition-transform {expandedDates.has(dateSlots.date) ? 'rotate-90' : ''}"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>
              <span class="font-semibold text-gray-900">
                {dateSlots.date} ({dateSlots.day_of_week})
              </span>
              {#if result.summary.available_dates.includes(dateSlots.date)}
                <span class="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full">
                  예약가능
                </span>
              {/if}
            </div>
            <div class="flex items-center gap-4">
              <span class="{getDateStatusColor(dateSlots)} font-medium">
                남음 {dateSlots.summary.total_remaining}/{dateSlots.summary.total_capacity}
              </span>
              <!-- 미니 진행률 바 -->
              <div class="w-24 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  class="{getProgressColor(dateSlots.summary.total_booked, dateSlots.summary.total_capacity)} h-full transition-all"
                  style="width: {getProgress(dateSlots.summary.total_booked, dateSlots.summary.total_capacity)}%"
                ></div>
              </div>
            </div>
          </button>

          <!-- 슬롯 목록 -->
          {#if expandedDates.has(dateSlots.date)}
            <div class="border-t border-gray-200 p-4">
              <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
                {#each dateSlots.slots as slot}
                  <div
                    class="px-3 py-2 rounded-lg border {getSlotBgColor(slot)} {getSlotBorderColor(slot)}"
                  >
                    <div class="flex items-center justify-between mb-1">
                      <span class="font-medium text-gray-900">{slot.time}</span>
                      <span class="{getSlotTextColor(slot)} text-sm font-semibold">
                        {#if slot.is_available}
                          {slot.remaining}석
                        {:else}
                          마감
                        {/if}
                      </span>
                    </div>
                    <!-- 진행률 바 -->
                    <div class="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        class="{getProgressColor(slot.booked, slot.capacity)} h-full transition-all"
                        style="width: {getProgress(slot.booked, slot.capacity)}%"
                      ></div>
                    </div>
                    <div class="text-xs text-gray-500 mt-1">
                      {slot.booked}/{slot.capacity}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/each}
    </div>

    <!-- 슬롯이 없을 때 -->
    {#if result.slots_by_date.length === 0}
      <div class="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
        <svg class="w-12 h-12 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <p class="text-gray-600">조회 기간 내 슬롯이 없습니다</p>
      </div>
    {/if}
  {/if}

  <!-- 초기 상태 -->
  {#if !result && !loading && !error}
    <div class="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
      <svg class="w-16 h-16 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <p class="text-gray-600 mb-2">네이버 예약 URL을 입력하고 조회 버튼을 클릭하세요</p>
      <p class="text-gray-400 text-sm">
        예: https://booking.naver.com/booking/13/bizes/1269828/items/6309738
      </p>
    </div>
  {/if}
</div>
