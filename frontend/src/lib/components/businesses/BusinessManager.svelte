<script lang="ts">
	import { Badge, Button } from '$lib/components/ui';

  import { onMount } from 'svelte';
  import { businessApi, itemApi, scheduleApi, serviceAccountApi } from '$lib/api';
  import type { Business, BusinessWithItems, BizItem, MonitorSchedule, ServiceAccountWithProfile } from '$lib/types';
  import SlotCheckModal from '$lib/components/SlotCheckModal.svelte';

  let businesses: Business[] = [];
  let accounts: ServiceAccountWithProfile[] = [];
  let loading = true;
  let error: string | null = null;

  // 선택된 업체/아이템
  let selectedBusiness: BusinessWithItems | null = null;
  let selectedItem: BizItem | null = null;
  let itemSchedules: MonitorSchedule[] = [];
  let loadingItems = false;
  let loadingSchedules = false;

  // 모달 상태
  let showAddBusinessModal = false;
  let showEditBusinessModal = false;
  let showAddItemModal = false;
  let showEditItemModal = false;
  let showAddScheduleModal = false;
  let showUrlImportModal = false;
  let showSlotCheckModal = false;
  let slotCheckBusiness: Business | null = null;
  let slotCheckItem: BizItem | null = null;

  // URL 임포트 폼
  let urlImport = {
    url: '',
    item_name: '',
    business_name: '',
    auto_booking_enabled: false,
    time_range: '',
    max_bookings_per_schedule: 1
  };
  let urlImportResult: { success: boolean; message: string; parsed_info?: Record<string, unknown> } | null = null;
  let urlImportLoading = false;

  // 폼 데이터
  let newBusiness = {
    business_id: '',
    business_type_id: '',
    name: '',
    category: 'default',
    service_type: 'naver',
    is_enabled: true
  };

  let editBusiness: Business | null = null;

  let newItem = {
    biz_item_id: '',
    name: '',
    time_range: '',
    is_enabled: true,
    auto_booking_enabled: false,
    max_bookings_per_schedule: 1
  };

  let editItem: BizItem | null = null;

  let newSchedule = {
    date: '',
    times: '',
    is_enabled: true,
    service_account_id: null as number | null
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

  async function fetchAccounts() {
    try {
      accounts = await serviceAccountApi.listActive('naver');
    } catch (e) {
      console.error('계정 목록 로드 실패:', e);
    }
  }

  async function selectBusiness(business: Business) {
    if (selectedBusiness?.id === business.id) {
      selectedBusiness = null;
      selectedItem = null;
      itemSchedules = [];
      return;
    }

    loadingItems = true;
    selectedItem = null;
    itemSchedules = [];
    try {
      selectedBusiness = await businessApi.get(business.id);
    } catch (e) {
      alert('아이템 로드 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    } finally {
      loadingItems = false;
    }
  }

  async function selectItem(item: BizItem) {
    if (selectedItem?.id === item.id) {
      selectedItem = null;
      itemSchedules = [];
      return;
    }

    loadingSchedules = true;
    selectedItem = item;
    try {
      itemSchedules = await itemApi.getSchedules(item.id);
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
      newBusiness = { business_id: '', business_type_id: '', name: '', category: 'default', service_type: 'naver', is_enabled: true };
      await fetchBusinesses();
    } catch (e) {
      alert('업체 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleUpdateBusiness() {
    if (!editBusiness) return;
    try {
      await businessApi.update(editBusiness.id, {
        name: editBusiness.name,
        category: editBusiness.category,
        is_enabled: editBusiness.is_enabled
      });
      showEditBusinessModal = false;
      editBusiness = null;
      await fetchBusinesses();
      if (selectedBusiness?.id) {
        selectedBusiness = await businessApi.get(selectedBusiness.id);
      }
    } catch (e) {
      alert('수정 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteBusiness(business: Business) {
    if (!confirm(`"${business.name}" 업체와 모든 하위 아이템/일정이 삭제됩니다. 계속하시겠습니까?`)) return;
    try {
      await businessApi.delete(business.id);
      await fetchBusinesses();
      if (selectedBusiness?.id === business.id) {
        selectedBusiness = null;
        selectedItem = null;
        itemSchedules = [];
      }
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleToggleBusinessEnabled(business: Business) {
    try {
      await businessApi.update(business.id, { is_enabled: !business.is_enabled });
      await fetchBusinesses();
    } catch (e) {
      alert('상태 변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleCreateItem() {
    if (!selectedBusiness) return;
    try {
      await itemApi.create(selectedBusiness.id, {
        biz_item_id: newItem.biz_item_id,
        name: newItem.name,
        time_range: newItem.time_range || undefined,
        is_enabled: newItem.is_enabled,
        auto_booking_enabled: newItem.auto_booking_enabled,
        max_bookings_per_schedule: newItem.max_bookings_per_schedule
      });
      showAddItemModal = false;
      newItem = { biz_item_id: '', name: '', time_range: '', is_enabled: true, auto_booking_enabled: false, max_bookings_per_schedule: 1 };
      selectedBusiness = await businessApi.get(selectedBusiness.id);
    } catch (e) {
      alert('아이템 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleUpdateItem() {
    if (!editItem || !selectedBusiness) return;
    try {
      await itemApi.update(editItem.id, {
        name: editItem.name,
        time_range: editItem.time_range || undefined,
        is_enabled: editItem.is_enabled,
        auto_booking_enabled: editItem.auto_booking_enabled,
        max_bookings_per_schedule: editItem.max_bookings_per_schedule
      });
      showEditItemModal = false;
      editItem = null;
      selectedBusiness = await businessApi.get(selectedBusiness.id);
    } catch (e) {
      alert('수정 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteItem(item: BizItem) {
    if (!confirm(`"${item.name}" 아이템과 모든 일정이 삭제됩니다. 계속하시겠습니까?`)) return;
    try {
      await itemApi.delete(item.id);
      if (selectedBusiness) {
        selectedBusiness = await businessApi.get(selectedBusiness.id);
      }
      if (selectedItem?.id === item.id) {
        selectedItem = null;
        itemSchedules = [];
      }
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleToggleItemEnabled(item: BizItem) {
    try {
      await itemApi.update(item.id, { is_enabled: !item.is_enabled });
      if (selectedBusiness) {
        selectedBusiness = await businessApi.get(selectedBusiness.id);
      }
    } catch (e) {
      alert('상태 변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleCreateSchedule() {
    if (!selectedItem) return;
    try {
      const times = newSchedule.times ? newSchedule.times.split(',').map(t => t.trim()) : [];
      await itemApi.createSchedule(selectedItem.id, {
        date: newSchedule.date,
        times: times,
        is_enabled: newSchedule.is_enabled,
        service_account_id: newSchedule.service_account_id
      });
      showAddScheduleModal = false;
      newSchedule = { date: '', times: '', is_enabled: true, service_account_id: null };
      itemSchedules = await itemApi.getSchedules(selectedItem.id);
    } catch (e) {
      alert('일정 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteSchedule(schedule: MonitorSchedule) {
    if (!confirm('이 일정을 삭제하시겠습니까?')) return;
    try {
      await scheduleApi.delete(schedule.id);
      if (selectedItem) {
        itemSchedules = await itemApi.getSchedules(selectedItem.id);
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
      if (selectedItem) {
        itemSchedules = await itemApi.getSchedules(selectedItem.id);
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


  async function handleUrlImport() {
    if (!urlImport.url || !urlImport.item_name) {
      alert('URL과 아이템명은 필수입니다.');
      return;
    }

    urlImportLoading = true;
    urlImportResult = null;
    try {
      const result = await businessApi.importFromUrl({
        url: urlImport.url,
        item_name: urlImport.item_name,
        business_name: urlImport.business_name || undefined,
        auto_booking_enabled: urlImport.auto_booking_enabled,
        time_range: urlImport.time_range || undefined,
        max_bookings_per_schedule: urlImport.max_bookings_per_schedule
      });
      urlImportResult = result;

      if (result.success) {
        await fetchBusinesses();
        // 성공 시 폼 초기화
        urlImport = {
          url: '',
          item_name: '',
          business_name: '',
          auto_booking_enabled: false,
          time_range: '',
          max_bookings_per_schedule: 1
        };
      }
    } catch (e) {
      urlImportResult = {
        success: false,
        message: e instanceof Error ? e.message : '임포트 실패'
      };
    } finally {
      urlImportLoading = false;
    }
  }

  onMount(() => {
    fetchBusinesses();
    fetchAccounts();
  });
</script>

<!-- 헤더 -->
<div class="mb-6 flex justify-between items-center">
  <div>
    <h3 class="text-lg font-semibold text-foreground">업체 관리</h3>
    <p class="text-sm text-muted-foreground">업체, 아이템, 모니터링 일정을 관리합니다</p>
  </div>
  <div class="flex gap-2">
    <Button variant="secondary" size="sm" on:click={fetchBusinesses}>
      새로고침
    </Button>
    <Button variant="success" size="sm" on:click={() => showUrlImportModal = true}>
      URL 임포트
    </Button>
    <Button variant="primary" size="sm" on:click={() => showAddBusinessModal = true}>
      + 업체 추가
    </Button>
  </div>
</div>

{#if loading}
  <div class="flex justify-center items-center h-64">
    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
  </div>
{:else if error}
  <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
    {error}
  </div>
{:else}
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <!-- 업체 목록 (왼쪽) -->
    <div class="card">
      <h3 class="text-lg font-semibold text-foreground mb-4">업체 목록 ({businesses.length})</h3>

      {#if businesses.length === 0}
        <p class="text-muted-foreground text-center py-4">등록된 업체가 없습니다.</p>
      {:else}
        <div class="overflow-x-auto">
          <table class="table table-sm">
            <thead>
              <tr>
                <th class="w-8"></th>
                <th>업체명</th>
                <th>서비스</th>
                <th class="w-20">작업</th>
              </tr>
            </thead>
            <tbody>
              {#each businesses as business (business.id)}
                <tr
                  class="cursor-pointer hover:bg-muted {selectedBusiness?.id === business.id ? 'bg-primary-light' : ''} {!business.is_enabled ? 'opacity-50' : ''}"
                  on:click={() => selectBusiness(business)}
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={business.is_enabled}
                      on:click|stopPropagation
                      on:change={() => handleToggleBusinessEnabled(business)}
                      title={business.is_enabled ? '비활성화' : '활성화'}
                    />
                  </td>
                  <td>
                    <div class="font-medium">{business.name}</div>
                    <div class="text-xs text-muted-foreground">{business.business_id}</div>
                  </td>
                  <td>
                    <Badge variant="info">{business.service_type}</Badge>
                  </td>
                  <td>
                    <div class="flex gap-1">
                      <Button variant="secondary" size="xs"
                        on:click={(e) => { e.stopPropagation(); { editBusiness = {...business }}; showEditBusinessModal = true; }}
                        title="수정"
                      >
                        ✏
                      </Button>
                      <Button
                        variant="destructive" size="xs"
                        on:click={(e) => { e.stopPropagation(); handleDeleteBusiness(business) }}
                        title="삭제"
                      >
                        🗑
                      </Button>
                    </div>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>

    <!-- 아이템 목록 (가운데) -->
    <div class="card">
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-lg font-semibold text-foreground">
          아이템 {#if selectedBusiness}({selectedBusiness.items?.length || 0}){/if}
        </h3>
        {#if selectedBusiness}
          <Button variant="secondary" size="sm" on:click={() => showAddItemModal = true}>
            + 추가
          </Button>
        {/if}
      </div>

      {#if !selectedBusiness}
        <p class="text-muted-foreground text-center py-8">업체를 선택하세요</p>
      {:else if loadingItems}
        <div class="flex justify-center py-8">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      {:else if !selectedBusiness.items || selectedBusiness.items.length === 0}
        <p class="text-muted-foreground text-center py-4">등록된 아이템이 없습니다.</p>
      {:else}
        <div class="overflow-x-auto">
          <table class="table table-sm">
            <thead>
              <tr>
                <th class="w-8"></th>
                <th>아이템명</th>
                <th>자동예약</th>
                <th class="w-20">작업</th>
              </tr>
            </thead>
            <tbody>
              {#each selectedBusiness.items as item (item.id)}
                <tr
                  class="cursor-pointer hover:bg-muted {selectedItem?.id === item.id ? 'bg-primary-light' : ''} {!item.is_enabled ? 'opacity-50' : ''}"
                  on:click={() => selectItem(item)}
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={item.is_enabled}
                      on:click|stopPropagation
                      on:change={() => handleToggleItemEnabled(item)}
                      title={item.is_enabled ? '비활성화' : '활성화'}
                    />
                  </td>
                  <td>
                    <div class="font-medium">{item.name}</div>
                    <div class="text-xs text-muted-foreground">{item.biz_item_id}</div>
                  </td>
                  <td>
                    {#if item.auto_booking_enabled}
                      <Badge variant="success">ON</Badge>
                    {:else}
                      <Badge variant="secondary">OFF</Badge>
                    {/if}
                  </td>
                  <td>
                    <div class="flex gap-1">
                      <Button variant="secondary" size="xs"
                        on:click={(e) => { e.stopPropagation(); {
                          slotCheckBusiness = selectedBusiness;
                          slotCheckItem = item;
                          showSlotCheckModal = true; }}}
                        title="슬롯 조회"
                      >
                        🔍
                      </Button>
                      <Button variant="secondary" size="xs"
                        on:click={(e) => { e.stopPropagation(); { editItem = {...item }}; showEditItemModal = true; }}
                        title="수정"
                      >
                        ✏
                      </Button>
                      <Button
                        variant="destructive" size="xs"
                        on:click={(e) => { e.stopPropagation(); handleDeleteItem(item) }}
                        title="삭제"
                      >
                        🗑
                      </Button>
                    </div>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>

    <!-- 일정 목록 (오른쪽) -->
    <div class="card">
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-lg font-semibold text-foreground">
          일정 {#if selectedItem}({itemSchedules.length}){/if}
        </h3>
        {#if selectedItem}
          <Button variant="secondary" size="sm" on:click={() => showAddScheduleModal = true}>
            + 추가
          </Button>
        {/if}
      </div>

      {#if !selectedItem}
        <p class="text-muted-foreground text-center py-8">아이템을 선택하세요</p>
      {:else if loadingSchedules}
        <div class="flex justify-center py-8">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      {:else if itemSchedules.length === 0}
        <p class="text-muted-foreground text-center py-4">등록된 일정이 없습니다.</p>
      {:else}
        <div class="space-y-2 max-h-96 overflow-y-auto">
          {#each itemSchedules as schedule (schedule.id)}
            {@const status = getStatusBadge(schedule.run_status, schedule.is_enabled)}
            <div class="flex items-center justify-between p-2 rounded bg-background {!schedule.is_enabled ? 'opacity-50' : ''}">
              <div class="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={schedule.is_enabled}
                  on:change={() => handleToggleSchedule(schedule)}
                />
                <div>
                  <div class="font-medium text-sm">{schedule.date}</div>
                  {#if schedule.times && schedule.times.length > 0}
                    <div class="text-xs text-muted-foreground">{schedule.times.join(', ')}</div>
                  {/if}
                  {#if schedule.account_name}
                    <Badge variant="info" class="text-xs">👤 {schedule.account_name}</Badge>
                  {/if}
                </div>
              </div>
              <div class="flex items-center gap-2">
                <span class="badge {status.class}">{status.text}</span>
                {#if schedule.booking_count > 0}
                  <span class="text-xs text-success">예약:{schedule.booking_count}</span>
                {/if}
                <button
                  class="text-error hover:text-error text-sm"
                  on:click={() => handleDeleteSchedule(schedule)}
                  title="삭제"
                >
                  ✕
                </button>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}

<!-- 업체 추가 모달 -->
{#if showAddBusinessModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">새 업체 추가</h3>
      </div>
      <form on:submit|preventDefault={handleCreateBusiness} class="p-4 space-y-4">
        <div>
          <label for="business_id" class="block text-sm font-medium text-foreground mb-1">Business ID (네이버)</label>
          <input id="business_id" type="text" class="input" bind:value={newBusiness.business_id} required placeholder="예: 1234567" />
        </div>
        <div>
          <label for="business_type_id" class="block text-sm font-medium text-foreground mb-1">Business Type ID</label>
          <input id="business_type_id" type="text" class="input" bind:value={newBusiness.business_type_id} required placeholder="예: 10" />
        </div>
        <div>
          <label for="name" class="block text-sm font-medium text-foreground mb-1">업체명</label>
          <input id="name" type="text" class="input" bind:value={newBusiness.name} required placeholder="표시 이름" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="service_type" class="block text-sm font-medium text-foreground mb-1">서비스</label>
            <select id="service_type" class="input" bind:value={newBusiness.service_type}>
              <option value="naver">네이버</option>
              <option value="coupang">쿠팡</option>
            </select>
          </div>
          <div>
            <label for="category" class="block text-sm font-medium text-foreground mb-1">카테고리</label>
            <input id="category" type="text" class="input" bind:value={newBusiness.category} placeholder="default" />
          </div>
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={newBusiness.is_enabled} />
          <span class="text-sm font-medium text-foreground">활성화</span>
        </label>
        <div class="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" on:click={() => showAddBusinessModal = false}>
            취소
          </Button>
          <Button type="submit" variant="primary">추가</Button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 업체 수정 모달 -->
{#if showEditBusinessModal && editBusiness}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">업체 수정</h3>
      </div>
      <form on:submit|preventDefault={handleUpdateBusiness} class="p-4 space-y-4">
        <div>
          <label class="block text-sm font-medium text-foreground mb-1">Business ID</label>
          <input type="text" class="input bg-muted" value={editBusiness.business_id} disabled />
        </div>
        <div>
          <label for="edit-name" class="block text-sm font-medium text-foreground mb-1">업체명</label>
          <input id="edit-name" type="text" class="input" bind:value={editBusiness.name} required />
        </div>
        <div>
          <label for="edit-category" class="block text-sm font-medium text-foreground mb-1">카테고리</label>
          <input id="edit-category" type="text" class="input" bind:value={editBusiness.category} />
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={editBusiness.is_enabled} />
          <span class="text-sm font-medium text-foreground">활성화</span>
        </label>
        <div class="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" on:click={() => { showEditBusinessModal = false; editBusiness = null; }}>
            취소
          </Button>
          <Button type="submit" variant="primary">저장</Button>
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
          <label for="biz_item_id" class="block text-sm font-medium text-foreground mb-1">Biz Item ID (네이버)</label>
          <input id="biz_item_id" type="text" class="input" bind:value={newItem.biz_item_id} required placeholder="예: 5001234" />
        </div>
        <div>
          <label for="item_name" class="block text-sm font-medium text-foreground mb-1">아이템명</label>
          <input id="item_name" type="text" class="input" bind:value={newItem.name} required placeholder="표시 이름" />
        </div>
        <div>
          <label for="time_range" class="block text-sm font-medium text-foreground mb-1">시간 범위</label>
          <input id="time_range" type="text" class="input" bind:value={newItem.time_range} placeholder="예: 10:00-21:00" />
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={newItem.is_enabled} />
          <span class="text-sm font-medium text-foreground">활성화</span>
        </label>
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={newItem.auto_booking_enabled} />
            <span class="text-sm font-medium text-foreground">자동 예약</span>
          </label>
          {#if newItem.auto_booking_enabled}
            <div class="flex items-center gap-2">
              <label for="max_bookings" class="text-sm text-foreground">최대 예약:</label>
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
          <Button type="button" variant="secondary" on:click={() => showAddItemModal = false}>
            취소
          </Button>
          <Button type="submit" variant="primary">추가</Button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 아이템 수정 모달 -->
{#if showEditItemModal && editItem}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">아이템 수정</h3>
      </div>
      <form on:submit|preventDefault={handleUpdateItem} class="p-4 space-y-4">
        <div>
          <label class="block text-sm font-medium text-foreground mb-1">Biz Item ID</label>
          <input type="text" class="input bg-muted" value={editItem.biz_item_id} disabled />
        </div>
        <div>
          <label for="edit-item-name" class="block text-sm font-medium text-foreground mb-1">아이템명</label>
          <input id="edit-item-name" type="text" class="input" bind:value={editItem.name} required />
        </div>
        <div>
          <label for="edit-time-range" class="block text-sm font-medium text-foreground mb-1">시간 범위</label>
          <input id="edit-time-range" type="text" class="input" bind:value={editItem.time_range} placeholder="예: 10:00-21:00" />
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={editItem.is_enabled} />
          <span class="text-sm font-medium text-foreground">활성화</span>
        </label>
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={editItem.auto_booking_enabled} />
            <span class="text-sm font-medium text-foreground">자동 예약</span>
          </label>
          {#if editItem.auto_booking_enabled}
            <div class="flex items-center gap-2">
              <label for="edit-max-bookings" class="text-sm text-foreground">최대 예약:</label>
              <input
                id="edit-max-bookings"
                type="number"
                class="input"
                style="width: 80px;"
                bind:value={editItem.max_bookings_per_schedule}
                min="1"
              />
            </div>
          {/if}
        </div>
        <div class="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" on:click={() => { showEditItemModal = false; editItem = null; }}>
            취소
          </Button>
          <Button type="submit" variant="primary">저장</Button>
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
          <label for="schedule_date" class="block text-sm font-medium text-foreground mb-1">날짜</label>
          <input id="schedule_date" type="date" class="input" bind:value={newSchedule.date} required />
        </div>
        <div>
          <label for="schedule_times" class="block text-sm font-medium text-foreground mb-1">시간 (쉼표 구분)</label>
          <input id="schedule_times" type="text" class="input" bind:value={newSchedule.times} placeholder="예: 10:00, 14:00, 18:00" />
        </div>
        <div>
          <label for="schedule_account_id" class="block text-sm font-medium text-foreground mb-1">사용 계정</label>
          <select id="schedule_account_id" class="input" bind:value={newSchedule.service_account_id}>
            <option value={null}>기본 계정</option>
            {#each accounts as account}
              <option value={account.id}>{account.profile_name} ({account.profile_dir})</option>
            {/each}
          </select>
          <p class="text-xs text-muted-foreground mt-1">이 일정을 실행할 때 사용할 계정을 선택하세요</p>
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={newSchedule.is_enabled} />
          <span class="text-sm font-medium text-foreground">활성화</span>
        </label>
        <div class="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" on:click={() => showAddScheduleModal = false}>
            취소
          </Button>
          <Button type="submit" variant="primary">추가</Button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- URL 임포트 모달 -->
{#if showUrlImportModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">URL로 임포트</h3>
        <p class="text-sm text-muted-foreground mt-1">
          네이버 예약 URL에서 업체/아이템/일정을 자동 생성합니다.
        </p>
      </div>
      <form on:submit|preventDefault={handleUrlImport} class="p-4 space-y-4">
        <div>
          <label for="import-url" class="block text-sm font-medium text-foreground mb-1">
            URL <span class="text-error">*</span>
          </label>
          <input
            id="import-url"
            type="text"
            class="input"
            bind:value={urlImport.url}
            required
            placeholder="https://booking.naver.com/booking/...?startDateTime=..."
          />
          <p class="text-xs text-muted-foreground mt-1">
            형식: /booking/{'{category}'}/bizes/{'{businessId}'}/items/{'{itemId}'}?startDateTime=...
          </p>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="import-item-name" class="block text-sm font-medium text-foreground mb-1">
              아이템명 <span class="text-error">*</span>
            </label>
            <input
              id="import-item-name"
              type="text"
              class="input"
              bind:value={urlImport.item_name}
              required
              placeholder="표시할 이름"
            />
          </div>
          <div>
            <label for="import-business-name" class="block text-sm font-medium text-foreground mb-1">
              업체명 (선택)
            </label>
            <input
              id="import-business-name"
              type="text"
              class="input"
              bind:value={urlImport.business_name}
              placeholder="없으면 자동 생성"
            />
          </div>
        </div>
        <div>
          <label for="import-time-range" class="block text-sm font-medium text-foreground mb-1">
            시간 범위 (선택)
          </label>
          <input
            id="import-time-range"
            type="text"
            class="input"
            bind:value={urlImport.time_range}
            placeholder="예: 18:00-21:00"
          />
        </div>
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={urlImport.auto_booking_enabled} />
            <span class="text-sm font-medium text-foreground">자동 예약</span>
          </label>
          {#if urlImport.auto_booking_enabled}
            <div class="flex items-center gap-2">
              <label for="import-max-bookings" class="text-sm text-foreground">최대 예약:</label>
              <input
                id="import-max-bookings"
                type="number"
                class="input"
                style="width: 80px;"
                bind:value={urlImport.max_bookings_per_schedule}
                min="1"
              />
            </div>
          {/if}
        </div>

        {#if urlImportResult}
          <div class="p-3 rounded-lg {urlImportResult.success ? 'bg-success-light border border-green-200' : 'bg-error-light border border-red-200'}">
            <p class="{urlImportResult.success ? 'text-success' : 'text-error'} font-medium">
              {urlImportResult.success ? '성공' : '실패'}
            </p>
            <p class="text-sm mt-1 {urlImportResult.success ? 'text-success' : 'text-error'}">
              {urlImportResult.message}
            </p>
            {#if urlImportResult.parsed_info}
              <div class="text-xs text-muted-foreground mt-2">
                <p>카테고리: {urlImportResult.parsed_info.category}</p>
                <p>업체ID: {urlImportResult.parsed_info.naver_business_id}</p>
                <p>아이템ID: {urlImportResult.parsed_info.naver_item_id}</p>
                {#if urlImportResult.parsed_info.date}
                  <p>날짜: {urlImportResult.parsed_info.date}</p>
                {/if}
              </div>
            {/if}
          </div>
        {/if}

        <div class="flex justify-end gap-2 pt-4">
          <Button
            type="button"
            variant="secondary"
            on:click={() => { showUrlImportModal = false; urlImportResult = null; }}
          >
            닫기
          </Button>
          <Button type="submit" variant="primary" disabled={urlImportLoading}>
            {urlImportLoading ? '처리 중...' : '임포트'}
          </Button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 슬롯 조회 모달 -->
<SlotCheckModal
  show={showSlotCheckModal}
  business={slotCheckBusiness}
  item={slotCheckItem}
  onClose={() => { showSlotCheckModal = false; slotCheckBusiness = null; slotCheckItem = null; }}
/>

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
  .table-sm th, .table-sm td {
    padding: 0.5rem;
    font-size: 0.875rem;
  }
  .btn-xs {
    padding: 0.125rem 0.375rem;
    font-size: 0.75rem;
  }
</style>
