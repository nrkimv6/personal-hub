<script lang="ts">
  import { onMount } from 'svelte';
  import { bookingApi, targetsApi } from '$lib/api';
  import type { MonitorTarget } from '$lib/types';

  let targets: MonitorTarget[] = [];
  let loading = true;
  let error: string | null = null;

  // 수동 예약 폼
  let manualBooking = {
    url: '',
    tag: '',
    slots: '',
    time_range: '',
    max_bookings: 1,
    dry_run: false
  };
  let bookingResult: { success: boolean; message: string } | null = null;
  let isBooking = false;

  // 슬롯 필터링 테스트
  let filterTest = {
    slots: '',
    time_range: '',
    result: null as { filtered_slots: string[]; original_count: number; filtered_count: number } | null
  };

  async function fetchTargets() {
    loading = true;
    try {
      targets = await targetsApi.list();
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  function getBookingTargets() {
    return targets.filter(t => t.auto_booking_enabled);
  }

  async function handleManualBooking() {
    isBooking = true;
    bookingResult = null;
    try {
      const slots = manualBooking.slots.split('\n').filter(s => s.trim());
      const result = await bookingApi.execute({
        url: manualBooking.url,
        tag: manualBooking.tag,
        slots,
        time_range: manualBooking.time_range || undefined,
        max_bookings: manualBooking.max_bookings,
        dry_run: manualBooking.dry_run
      });
      bookingResult = result;
    } catch (e) {
      bookingResult = {
        success: false,
        message: e instanceof Error ? e.message : '예약 실패'
      };
    } finally {
      isBooking = false;
    }
  }

  async function handleFilterTest() {
    try {
      const slots = filterTest.slots.split('\n').filter(s => s.trim());
      filterTest.result = await bookingApi.filterSlots(slots, filterTest.time_range);
    } catch (e) {
      alert('필터링 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleResetBookingCount(url: string) {
    if (!confirm('예약 횟수를 초기화하시겠습니까?')) return;
    try {
      await bookingApi.reset(url);
      await fetchTargets();
    } catch (e) {
      alert('초기화 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleToggleAutoBooking(target: MonitorTarget) {
    try {
      await targetsApi.update(target.id, {
        auto_booking_enabled: !target.auto_booking_enabled
      });
      await fetchTargets();
    } catch (e) {
      alert('변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  onMount(fetchTargets);
</script>

<div class="p-6">
  <div class="mb-6">
    <h2 class="text-2xl font-bold text-gray-900">예약 관리</h2>
  </div>

  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <!-- 수동 예약 -->
    <div class="card">
      <h3 class="text-lg font-semibold text-gray-900 mb-4">수동 예약 실행</h3>
      <form on:submit|preventDefault={handleManualBooking} class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">URL</label>
          <input
            type="url"
            class="input"
            bind:value={manualBooking.url}
            required
            placeholder="https://booking.naver.com/..."
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">태그 (표시용)</label>
          <input
            type="text"
            class="input"
            bind:value={manualBooking.tag}
            required
            placeholder="예약 대상 이름"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            슬롯 목록 (한 줄에 하나씩)
          </label>
          <textarea
            class="input h-32"
            bind:value={manualBooking.slots}
            required
            placeholder="2025-12-10 18:00:00 (2매)&#10;2025-12-10 19:00:00 (3매)"
          ></textarea>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">시간 범위</label>
            <input
              type="text"
              class="input"
              bind:value={manualBooking.time_range}
              placeholder="18:00-21:00"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">최대 예약 수</label>
            <input
              type="number"
              class="input"
              bind:value={manualBooking.max_bookings}
              min="1"
            />
          </div>
        </div>
        <div class="flex items-center gap-2">
          <input type="checkbox" id="dry_run" bind:checked={manualBooking.dry_run} />
          <label for="dry_run" class="text-sm font-medium text-gray-700">
            테스트 모드 (실제 예약 안함)
          </label>
        </div>
        <button type="submit" class="btn btn-primary w-full" disabled={isBooking}>
          {isBooking ? '예약 중...' : '📅 예약 실행'}
        </button>
      </form>

      {#if bookingResult}
        <div class="mt-4 p-4 rounded-lg {bookingResult.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}">
          <p class="{bookingResult.success ? 'text-green-800' : 'text-red-800'} font-medium">
            {bookingResult.success ? '✅ 성공' : '❌ 실패'}
          </p>
          <p class="text-sm mt-1 {bookingResult.success ? 'text-green-600' : 'text-red-600'}">
            {bookingResult.message}
          </p>
        </div>
      {/if}
    </div>

    <!-- 슬롯 필터링 테스트 -->
    <div class="card">
      <h3 class="text-lg font-semibold text-gray-900 mb-4">슬롯 필터링 테스트</h3>
      <form on:submit|preventDefault={handleFilterTest} class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">
            슬롯 목록 (한 줄에 하나씩)
          </label>
          <textarea
            class="input h-32"
            bind:value={filterTest.slots}
            required
            placeholder="2025-12-10 18:00:00 (2매)&#10;2025-12-10 19:00:00 (3매)"
          ></textarea>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">시간 범위</label>
          <input
            type="text"
            class="input"
            bind:value={filterTest.time_range}
            required
            placeholder="18:00-21:00"
          />
        </div>
        <button type="submit" class="btn btn-secondary w-full">🔍 필터링 테스트</button>
      </form>

      {#if filterTest.result}
        <div class="mt-4 p-4 bg-gray-50 rounded-lg">
          <p class="text-sm text-gray-600">
            원본: {filterTest.result.original_count}개 → 필터링: {filterTest.result.filtered_count}개
          </p>
          {#if filterTest.result.filtered_slots.length > 0}
            <ul class="mt-2 text-sm space-y-1">
              {#each filterTest.result.filtered_slots as slot}
                <li class="text-green-600">✓ {slot}</li>
              {/each}
            </ul>
          {:else}
            <p class="text-sm text-yellow-600 mt-2">조건에 맞는 슬롯이 없습니다.</p>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  <!-- 자동 예약 대상 목록 -->
  <div class="card mt-6">
    <div class="flex justify-between items-center mb-4">
      <h3 class="text-lg font-semibold text-gray-900">자동 예약 대상</h3>
      <button class="btn btn-secondary btn-sm" on:click={fetchTargets}>
        🔄 새로고침
      </button>
    </div>

    {#if loading}
      <div class="flex justify-center py-8">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    {:else if error}
      <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
        {error}
      </div>
    {:else}
      <table class="table">
        <thead>
          <tr>
            <th>라벨</th>
            <th>상태</th>
            <th>시간 범위</th>
            <th>예약 현황</th>
            <th>마지막 예약</th>
            <th>작업</th>
          </tr>
        </thead>
        <tbody>
          {#each getBookingTargets() as target (target.id)}
            <tr>
              <td class="font-medium">{target.label}</td>
              <td>
                {#if target.auto_booking_enabled}
                  <span class="badge badge-success">활성</span>
                {:else}
                  <span class="badge badge-gray">비활성</span>
                {/if}
              </td>
              <td class="text-sm text-gray-500">
                {target.time_range || '-'}
              </td>
              <td>
                <span class="font-medium">{target.booking_count}</span>
                <span class="text-gray-400">/ {target.max_bookings}</span>
              </td>
              <td class="text-sm text-gray-500">
                {#if target.last_booking_time}
                  {new Date(target.last_booking_time).toLocaleString('ko-KR')}
                {:else}
                  -
                {/if}
              </td>
              <td>
                <div class="flex gap-1">
                  <button
                    class="btn btn-sm {target.auto_booking_enabled ? 'btn-secondary' : 'btn-success'}"
                    on:click={() => handleToggleAutoBooking(target)}
                  >
                    {target.auto_booking_enabled ? '⏸ 중지' : '▶ 활성화'}
                  </button>
                  <button
                    class="btn btn-secondary btn-sm"
                    on:click={() => handleResetBookingCount(target.url)}
                  >
                    🔄 초기화
                  </button>
                </div>
              </td>
            </tr>
          {:else}
            <tr>
              <td colspan="6" class="text-center text-gray-500 py-8">
                자동 예약이 활성화된 대상이 없습니다.
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>
