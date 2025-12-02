<script lang="ts">
  import { onMount } from 'svelte';
  import { businessApi, itemApi, scheduleApi } from '$lib/api';
  import type { Business, BusinessWithItems, BizItem, MonitorSchedule } from '$lib/types';

  let businesses: Business[] = [];
  let loading = true;
  let error: string | null = null;

  // 확장된 업체 (아이템 표시)
  let expandedBusinessId: number | null = null;
  let expandedBusiness: BusinessWithItems | null = null;
  let loadingItems = false;

  // 확장된 아이템 (일정 표시)
  let expandedItemId: number | null = null;
  let expandedItemSchedules: MonitorSchedule[] = [];
  let loadingSchedules = false;

  // 모달 상태
  let showAddBusinessModal = false;
  let showAddItemModal = false;
  let showAddScheduleModal = false;

  // 폼 데이터
  let newBusiness = {
    business_id: '',
    business_type_id: '',
    name: '',
    category: 'default',
    service_type: 'naver'
  };

  let newItem = {
    biz_item_id: '',
    name: '',
    time_range: '',
    auto_booking_enabled: false,
    max_bookings_per_schedule: 1
  };

  let newSchedule = {
    date: '',
    times: '',
    is_enabled: true
  };

  async function fetchBusinesses() {
    loading = true;
    try {
      businesses = await businessApi.list();
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  async function toggleBusinessExpand(businessId: number) {
    if (expandedBusinessId === businessId) {
      expandedBusinessId = null;
      expandedBusiness = null;
      expandedItemId = null;
      return;
    }

    loadingItems = true;
    expandedBusinessId = businessId;
    expandedItemId = null;
    try {
      expandedBusiness = await businessApi.get(businessId);
    } catch (e) {
      alert('아이템 로드 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    } finally {
      loadingItems = false;
    }
  }

  async function toggleItemExpand(itemId: number) {
    if (expandedItemId === itemId) {
      expandedItemId = null;
      expandedItemSchedules = [];
      return;
    }

    loadingSchedules = true;
    expandedItemId = itemId;
    try {
      expandedItemSchedules = await itemApi.getSchedules(itemId);
    } catch (e) {
      alert('일정 로드 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    } finally {
      loadingSchedules = false;
    }
  }

  async function handleCreateBusiness() {
    try {
      await businessApi.create(newBusiness);
      showAddBusinessModal = false;
      newBusiness = { business_id: '', business_type_id: '', name: '', category: 'default', service_type: 'naver' };
      await fetchBusinesses();
    } catch (e) {
      alert('업체 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteBusiness(id: number) {
    if (!confirm('이 업체와 모든 하위 아이템/일정이 삭제됩니다. 계속하시겠습니까?')) return;
    try {
      await businessApi.delete(id);
      await fetchBusinesses();
      if (expandedBusinessId === id) {
        expandedBusinessId = null;
        expandedBusiness = null;
      }
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleCreateItem() {
    if (!expandedBusinessId) return;
    try {
      await itemApi.create(expandedBusinessId, {
        biz_item_id: newItem.biz_item_id,
        name: newItem.name,
        time_range: newItem.time_range || undefined,
        auto_booking_enabled: newItem.auto_booking_enabled,
        max_bookings_per_schedule: newItem.max_bookings_per_schedule
      });
      showAddItemModal = false;
      newItem = { biz_item_id: '', name: '', time_range: '', auto_booking_enabled: false, max_bookings_per_schedule: 1 };
      // 아이템 목록 새로고침
      expandedBusiness = await businessApi.get(expandedBusinessId);
    } catch (e) {
      alert('아이템 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteItem(itemId: number) {
    if (!confirm('이 아이템과 모든 일정이 삭제됩니다. 계속하시겠습니까?')) return;
    try {
      await itemApi.delete(itemId);
      if (expandedBusinessId) {
        expandedBusiness = await businessApi.get(expandedBusinessId);
      }
      if (expandedItemId === itemId) {
        expandedItemId = null;
        expandedItemSchedules = [];
      }
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleCreateSchedule() {
    if (!expandedItemId) return;
    try {
      const times = newSchedule.times ? newSchedule.times.split(',').map(t => t.trim()) : [];
      await itemApi.createSchedule(expandedItemId, {
        date: newSchedule.date,
        times: times,
        is_enabled: newSchedule.is_enabled
      });
      showAddScheduleModal = false;
      newSchedule = { date: '', times: '', is_enabled: true };
      expandedItemSchedules = await itemApi.getSchedules(expandedItemId);
    } catch (e) {
      alert('일정 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteSchedule(scheduleId: number) {
    if (!confirm('이 일정을 삭제하시겠습니까?')) return;
    try {
      await scheduleApi.delete(scheduleId);
      if (expandedItemId) {
        expandedItemSchedules = await itemApi.getSchedules(expandedItemId);
      }
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleToggleSchedule(schedule: MonitorSchedule) {
    try {
      if (schedule.is_enabled) {
        await scheduleApi.disable(schedule.id);
      } else {
        await scheduleApi.enable(schedule.id);
      }
      if (expandedItemId) {
        expandedItemSchedules = await itemApi.getSchedules(expandedItemId);
      }
    } catch (e) {
      alert('상태 변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  function getStatusBadge(status: string, isEnabled: boolean) {
    if (!isEnabled) return { class: 'badge-gray', text: '비활성' };
    switch (status) {
      case 'running': return { class: 'badge-success', text: '실행 중' };
      case 'queued': return { class: 'badge-info', text: '대기 중' };
      case 'pending': return { class: 'badge-warning', text: '시작 대기' };
      case 'error': return { class: 'badge-error', text: '오류' };
      case 'paused': return { class: 'badge-warning', text: '일시 중지' };
      case 'stopped': return { class: 'badge-gray', text: '중지됨' };
      default: return { class: 'badge-gray', text: '대기' };
    }
  }

  onMount(fetchBusinesses);
</script>

<div class="p-6">
  <div class="mb-6 flex justify-between items-center">
    <h2 class="text-2xl font-bold text-gray-900">업체 관리</h2>
    <div class="flex gap-2">
      <button class="btn btn-secondary btn-sm" on:click={fetchBusinesses}>
        새로고침
      </button>
      <button class="btn btn-primary" on:click={() => showAddBusinessModal = true}>
        + 업체 추가
      </button>
    </div>
  </div>

  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else if businesses.length === 0}
    <div class="card text-center py-8">
      <p class="text-gray-500 mb-4">등록된 업체가 없습니다.</p>
      <button class="btn btn-primary" on:click={() => showAddBusinessModal = true}>
        첫 업체 추가하기
      </button>
    </div>
  {:else}
    <div class="space-y-4">
      {#each businesses as business (business.id)}
        <div class="card">
          <!-- 업체 헤더 -->
          <div class="flex items-center justify-between">
            <button
              class="flex-1 text-left flex items-center gap-3"
              on:click={() => toggleBusinessExpand(business.id)}
            >
              <span class="text-lg">{expandedBusinessId === business.id ? '▼' : '▶'}</span>
              <div>
                <h3 class="font-semibold text-gray-900">{business.name}</h3>
                <p class="text-sm text-gray-500">
                  {business.business_id} | {business.service_type} | {business.category}
                </p>
              </div>
            </button>
            <button
              class="btn btn-danger btn-sm"
              on:click={() => handleDeleteBusiness(business.id)}
            >
              삭제
            </button>
          </div>

          <!-- 아이템 목록 (확장 시) -->
          {#if expandedBusinessId === business.id}
            <div class="mt-4 pl-8 border-l-2 border-gray-200">
              {#if loadingItems}
                <div class="py-4 text-center text-gray-500">로딩 중...</div>
              {:else if expandedBusiness && expandedBusiness.items}
                <div class="flex justify-between items-center mb-3">
                  <h4 class="font-medium text-gray-700">아이템 ({expandedBusiness.items.length})</h4>
                  <button class="btn btn-secondary btn-sm" on:click={() => showAddItemModal = true}>
                    + 아이템 추가
                  </button>
                </div>

                {#if expandedBusiness.items.length === 0}
                  <p class="text-gray-500 py-2">등록된 아이템이 없습니다.</p>
                {:else}
                  <div class="space-y-3">
                    {#each expandedBusiness.items as item (item.id)}
                      <div class="bg-gray-50 rounded-lg p-3">
                        <!-- 아이템 헤더 -->
                        <div class="flex items-center justify-between">
                          <button
                            class="flex-1 text-left flex items-center gap-2"
                            on:click={() => toggleItemExpand(item.id)}
                          >
                            <span>{expandedItemId === item.id ? '▼' : '▶'}</span>
                            <div>
                              <span class="font-medium">{item.name}</span>
                              <span class="text-sm text-gray-500 ml-2">({item.biz_item_id})</span>
                              {#if item.auto_booking_enabled}
                                <span class="badge badge-success ml-2">자동예약</span>
                              {/if}
                            </div>
                          </button>
                          <button
                            class="btn btn-danger btn-sm"
                            on:click={() => handleDeleteItem(item.id)}
                          >
                            삭제
                          </button>
                        </div>

                        <!-- 일정 목록 (확장 시) -->
                        {#if expandedItemId === item.id}
                          <div class="mt-3 pl-6 border-l-2 border-gray-300">
                            {#if loadingSchedules}
                              <div class="py-2 text-center text-gray-500">로딩 중...</div>
                            {:else}
                              <div class="flex justify-between items-center mb-2">
                                <h5 class="text-sm font-medium text-gray-600">일정 ({expandedItemSchedules.length})</h5>
                                <button class="btn btn-secondary btn-sm" on:click={() => showAddScheduleModal = true}>
                                  + 일정 추가
                                </button>
                              </div>

                              {#if expandedItemSchedules.length === 0}
                                <p class="text-gray-500 text-sm py-2">등록된 일정이 없습니다.</p>
                              {:else}
                                <div class="space-y-2">
                                  {#each expandedItemSchedules as schedule (schedule.id)}
                                    {@const status = getStatusBadge(schedule.run_status, schedule.is_enabled)}
                                    <div class="flex items-center justify-between bg-white rounded p-2 text-sm {!schedule.is_enabled ? 'opacity-50' : ''}">
                                      <div class="flex items-center gap-3">
                                        <input
                                          type="checkbox"
                                          checked={schedule.is_enabled}
                                          on:change={() => handleToggleSchedule(schedule)}
                                        />
                                        <span class="font-medium">{schedule.date}</span>
                                        <span class="badge {status.class}">{status.text}</span>
                                        {#if schedule.times && schedule.times.length > 0}
                                          <span class="text-gray-500">{schedule.times.join(', ')}</span>
                                        {/if}
                                        {#if schedule.booking_count > 0}
                                          <span class="text-green-600">예약: {schedule.booking_count}</span>
                                        {/if}
                                      </div>
                                      <button
                                        class="text-red-500 hover:text-red-700"
                                        on:click={() => handleDeleteSchedule(schedule.id)}
                                      >
                                        X
                                      </button>
                                    </div>
                                  {/each}
                                </div>
                              {/if}
                            {/if}
                          </div>
                        {/if}
                      </div>
                    {/each}
                  </div>
                {/if}
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<!-- 업체 추가 모달 -->
{#if showAddBusinessModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">새 업체 추가</h3>
      </div>
      <form on:submit|preventDefault={handleCreateBusiness} class="p-4 space-y-4">
        <div>
          <label for="business_id" class="block text-sm font-medium text-gray-700 mb-1">Business ID (네이버)</label>
          <input id="business_id" type="text" class="input" bind:value={newBusiness.business_id} required placeholder="예: 1234567" />
        </div>
        <div>
          <label for="business_type_id" class="block text-sm font-medium text-gray-700 mb-1">Business Type ID</label>
          <input id="business_type_id" type="text" class="input" bind:value={newBusiness.business_type_id} required placeholder="예: 10" />
        </div>
        <div>
          <label for="name" class="block text-sm font-medium text-gray-700 mb-1">업체명</label>
          <input id="name" type="text" class="input" bind:value={newBusiness.name} required placeholder="표시 이름" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="service_type" class="block text-sm font-medium text-gray-700 mb-1">서비스</label>
            <select id="service_type" class="input" bind:value={newBusiness.service_type}>
              <option value="naver">네이버</option>
              <option value="coupang">쿠팡</option>
            </select>
          </div>
          <div>
            <label for="category" class="block text-sm font-medium text-gray-700 mb-1">카테고리</label>
            <input id="category" type="text" class="input" bind:value={newBusiness.category} placeholder="default" />
          </div>
        </div>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" on:click={() => showAddBusinessModal = false}>
            취소
          </button>
          <button type="submit" class="btn btn-primary">추가</button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 아이템 추가 모달 -->
{#if showAddItemModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">새 아이템 추가</h3>
      </div>
      <form on:submit|preventDefault={handleCreateItem} class="p-4 space-y-4">
        <div>
          <label for="biz_item_id" class="block text-sm font-medium text-gray-700 mb-1">Biz Item ID (네이버)</label>
          <input id="biz_item_id" type="text" class="input" bind:value={newItem.biz_item_id} required placeholder="예: 5001234" />
        </div>
        <div>
          <label for="item_name" class="block text-sm font-medium text-gray-700 mb-1">아이템명</label>
          <input id="item_name" type="text" class="input" bind:value={newItem.name} required placeholder="표시 이름" />
        </div>
        <div>
          <label for="time_range" class="block text-sm font-medium text-gray-700 mb-1">시간 범위</label>
          <input id="time_range" type="text" class="input" bind:value={newItem.time_range} placeholder="예: 10:00-21:00" />
        </div>
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={newItem.auto_booking_enabled} />
            <span class="text-sm font-medium text-gray-700">자동 예약</span>
          </label>
          {#if newItem.auto_booking_enabled}
            <div class="flex items-center gap-2">
              <label for="max_bookings" class="text-sm text-gray-700">최대 예약:</label>
              <input
                id="max_bookings"
                type="number"
                class="input"
                style="width: 80px;"
                bind:value={newItem.max_bookings_per_schedule}
                min="1"
              />
            </div>
          {/if}
        </div>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" on:click={() => showAddItemModal = false}>
            취소
          </button>
          <button type="submit" class="btn btn-primary">추가</button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 일정 추가 모달 -->
{#if showAddScheduleModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">새 일정 추가</h3>
      </div>
      <form on:submit|preventDefault={handleCreateSchedule} class="p-4 space-y-4">
        <div>
          <label for="schedule_date" class="block text-sm font-medium text-gray-700 mb-1">날짜</label>
          <input id="schedule_date" type="date" class="input" bind:value={newSchedule.date} required />
        </div>
        <div>
          <label for="schedule_times" class="block text-sm font-medium text-gray-700 mb-1">시간 (쉼표 구분)</label>
          <input id="schedule_times" type="text" class="input" bind:value={newSchedule.times} placeholder="예: 10:00, 14:00, 18:00" />
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={newSchedule.is_enabled} />
          <span class="text-sm font-medium text-gray-700">활성화</span>
        </label>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" on:click={() => showAddScheduleModal = false}>
            취소
          </button>
          <button type="submit" class="btn btn-primary">추가</button>
        </div>
      </form>
    </div>
  </div>
{/if}

<style>
  .badge {
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
  }
  .badge-success {
    background-color: #dcfce7;
    color: #166534;
  }
  .badge-info {
    background-color: #dbeafe;
    color: #1e40af;
  }
  .badge-warning {
    background-color: #fef9c3;
    color: #854d0e;
  }
  .badge-error {
    background-color: #fee2e2;
    color: #991b1b;
  }
  .badge-gray {
    background-color: #f3f4f6;
    color: #4b5563;
  }
</style>
