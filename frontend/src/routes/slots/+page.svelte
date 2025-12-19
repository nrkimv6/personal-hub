<script lang="ts">
  import { onMount } from 'svelte';
  import { slotApi, businessApi, monitoringEventApi } from '$lib/api';
  import type { SlotCheckResponse, DateSlots, SlotInfo, Business, BizItem, MonitoringEventStats } from '$lib/types';

  // 입력 모드: 'select' (등록된 상품) 또는 'url' (URL 입력)
  let inputMode = $state<'select' | 'url'>('select');

  // URL 입력 모드
  let url = $state('');

  // 등록된 상품 선택 모드
  let businesses = $state<Business[]>([]);
  let selectedBusinessId = $state<number | null>(null);
  let bizItems = $state<BizItem[]>([]);
  let selectedItem = $state<BizItem | null>(null);
  let loadingBusinesses = $state(false);
  let loadingItems = $state(false);

  // 공통 옵션
  let targetDate = $state('');
  let daysAhead = $state(14);

  // 조회 상태
  let loading = $state(false);
  let error = $state<string | null>(null);
  let result = $state<SlotCheckResponse | null>(null);

  // 모니터링 통계
  let monitoringStats = $state<MonitoringEventStats | null>(null);
  let loadingStats = $state(false);

  // 날짜별 접기/펼치기 상태
  let expandedDates = $state<Set<string>>(new Set());

  // 페이지 마운트 시 초기화
  onMount(async () => {
    // localStorage에서 마지막 선택한 모드 복원
    const savedMode = localStorage.getItem('slotCheckInputMode');
    if (savedMode === 'url' || savedMode === 'select') {
      inputMode = savedMode;
    }

    // 업체 목록 로드
    await loadBusinesses();
  });

  // 입력 모드 변경 시 저장
  function setInputMode(mode: 'select' | 'url') {
    inputMode = mode;
    localStorage.setItem('slotCheckInputMode', mode);
    error = null;
  }

  // 업체 목록 로드
  async function loadBusinesses() {
    loadingBusinesses = true;
    try {
      businesses = await businessApi.list();
    } catch (e) {
      console.error('Failed to load businesses:', e);
    } finally {
      loadingBusinesses = false;
    }
  }

  // 업체 선택 시 상품 목록 로드
  async function onBusinessChange(businessId: number) {
    selectedBusinessId = businessId;
    selectedItem = null;
    bizItems = [];
    loadingItems = true;
    try {
      bizItems = await businessApi.getItems(businessId);
    } catch (e) {
      console.error('Failed to load items:', e);
    } finally {
      loadingItems = false;
    }
  }

  // 상품 선택
  function onItemChange(item: BizItem) {
    selectedItem = item;
  }

  // 슬롯 조회
  async function checkSlots() {
    if (inputMode === 'url') {
      if (!url) {
        error = 'URL을 입력해주세요';
        return;
      }
    } else {
      if (!selectedItem) {
        error = '상품을 선택해주세요';
        return;
      }
    }

    loading = true;
    error = null;
    result = null;
    monitoringStats = null;

    try {
      if (inputMode === 'url') {
        result = await slotApi.check({
          url,
          target_date: targetDate || undefined,
          days_ahead: daysAhead
        });
      } else {
        // 등록된 상품에서 business 정보 가져오기
        const business = businesses.find(b => b.id === selectedBusinessId);
        result = await slotApi.check({
          business_id: business?.business_id,
          biz_item_id: selectedItem!.biz_item_id,
          target_date: targetDate || undefined,
          days_ahead: daysAhead
        });

        // 등록된 상품인 경우 모니터링 통계도 로드
        await loadMonitoringStats();
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

  // 모니터링 통계 로드
  async function loadMonitoringStats() {
    if (!selectedItem) return;

    loadingStats = true;
    try {
      const startDate = targetDate || getTodayDate();
      const endDate = addDays(startDate, daysAhead);

      monitoringStats = await monitoringEventApi.stats({
        biz_item_id: selectedItem.id,
        date_from: startDate,
        date_to: endDate
      });
    } catch (e) {
      console.error('Failed to load monitoring stats:', e);
    } finally {
      loadingStats = false;
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

  // 날짜 더하기
  function addDays(dateStr: string, days: number): string {
    const date = new Date(dateStr);
    date.setDate(date.getDate() + days);
    return date.toISOString().split('T')[0];
  }

  // 재고 발견률 계산
  function getAvailableRate(): string {
    if (!monitoringStats || monitoringStats.total_checks === 0) return '0';
    return ((monitoringStats.available_count / monitoringStats.total_checks) * 100).toFixed(1);
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
    <!-- 탭 UI -->
    <div class="flex border-b border-gray-200 mb-4">
      <button
        onclick={() => setInputMode('select')}
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors {inputMode === 'select'
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
      >
        등록된 상품
      </button>
      <button
        onclick={() => setInputMode('url')}
        class="px-4 py-2 text-sm font-medium border-b-2 transition-colors {inputMode === 'url'
          ? 'border-blue-500 text-blue-600'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
      >
        URL 입력
      </button>
    </div>

    <!-- 등록된 상품 선택 -->
    {#if inputMode === 'select'}
      <div class="space-y-4">
        <!-- 업체 선택 -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">업체</label>
          {#if loadingBusinesses}
            <div class="text-gray-500 text-sm">로딩 중...</div>
          {:else if businesses.length === 0}
            <div class="text-gray-500 text-sm p-3 bg-gray-50 rounded-lg">
              등록된 업체가 없습니다. 먼저 업체를 등록해주세요.
            </div>
          {:else}
            <select
              class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              onchange={(e) => {
                const target = e.target as HTMLSelectElement;
                if (target.value) onBusinessChange(Number(target.value));
              }}
            >
              <option value="">업체를 선택하세요</option>
              {#each businesses as business}
                <option value={business.id}>{business.name}</option>
              {/each}
            </select>
          {/if}
        </div>

        <!-- 상품 선택 -->
        {#if selectedBusinessId}
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">상품</label>
            {#if loadingItems}
              <div class="text-gray-500 text-sm">로딩 중...</div>
            {:else if bizItems.length === 0}
              <div class="text-gray-500 text-sm p-3 bg-gray-50 rounded-lg">
                이 업체에 등록된 상품이 없습니다.
              </div>
            {:else}
              <select
                class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                onchange={(e) => {
                  const target = e.target as HTMLSelectElement;
                  const item = bizItems.find(i => i.id === Number(target.value));
                  if (item) onItemChange(item);
                }}
              >
                <option value="">상품을 선택하세요</option>
                {#each bizItems as item}
                  <option value={item.id}>{item.name}</option>
                {/each}
              </select>
            {/if}
          </div>
        {/if}
      </div>
    {:else}
      <!-- URL 입력 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">네이버 예약 URL</label>
        <input
          type="text"
          bind:value={url}
          onkeydown={handleKeydown}
          placeholder="https://booking.naver.com/booking/13/bizes/..."
          class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>
    {/if}

    <!-- 옵션 및 조회 버튼 -->
    <div class="mt-4 pt-4 border-t border-gray-200">
      <div class="flex flex-wrap items-center gap-4">
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

        <button
          onclick={checkSlots}
          disabled={loading}
          class="ml-auto px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
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

    <!-- 모니터링 이력 (등록된 상품인 경우만) -->
    {#if inputMode === 'select' && selectedItem}
      <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <h3 class="text-sm font-semibold text-gray-700 mb-3">모니터링 이력</h3>
        {#if loadingStats}
          <div class="text-gray-500 text-sm">통계 로딩 중...</div>
        {:else if monitoringStats && monitoringStats.total_checks > 0}
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="p-3 bg-gray-50 rounded-lg">
              <p class="text-xs text-gray-500">총 체크</p>
              <p class="text-lg font-bold text-gray-900">{monitoringStats.total_checks.toLocaleString()}회</p>
            </div>
            <div class="p-3 bg-green-50 rounded-lg">
              <p class="text-xs text-gray-500">재고 발견</p>
              <p class="text-lg font-bold text-green-600">
                {monitoringStats.available_count}회
                <span class="text-sm font-normal">({getAvailableRate()}%)</span>
              </p>
            </div>
            <div class="p-3 bg-blue-50 rounded-lg">
              <p class="text-xs text-gray-500">평균 응답</p>
              <p class="text-lg font-bold text-blue-600">
                {monitoringStats.avg_response_time_ms ? Math.round(monitoringStats.avg_response_time_ms) : '-'}ms
              </p>
            </div>
            <div class="p-3 bg-gray-50 rounded-lg">
              <p class="text-xs text-gray-500">마지막 체크</p>
              <p class="text-sm font-medium text-gray-700">
                {monitoringStats.last_check_time
                  ? new Date(monitoringStats.last_check_time).toLocaleString('ko-KR')
                  : '-'}
              </p>
            </div>
          </div>
        {:else}
          <div class="text-gray-500 text-sm p-3 bg-gray-50 rounded-lg">
            이 상품에 대한 모니터링 이력이 없습니다.
          </div>
        {/if}
      </div>
    {/if}

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
      {#if inputMode === 'select'}
        <p class="text-gray-600 mb-2">업체와 상품을 선택하고 조회 버튼을 클릭하세요</p>
      {:else}
        <p class="text-gray-600 mb-2">네이버 예약 URL을 입력하고 조회 버튼을 클릭하세요</p>
        <p class="text-gray-400 text-sm">
          예: https://booking.naver.com/booking/13/bizes/1269828/items/6309738
        </p>
      {/if}
    </div>
  {/if}
</div>
