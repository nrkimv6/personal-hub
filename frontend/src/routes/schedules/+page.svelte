<script lang="ts">
  import { onMount } from 'svelte';
  import { scheduleApi, businessApi, accountApi, itemApi } from '$lib/api';
  import type { ScheduleWithContext, Business, BusinessWithItems, BizItem, Account, MonitorScheduleUpdate, MonitorScheduleCreate } from '$lib/types';

  let schedules: ScheduleWithContext[] = [];
  let businesses: Business[] = [];
  let accounts: Account[] = [];
  let loading = true;
  let error: string | null = null;

  // 오늘 날짜 계산
  function getTodayDate(): string {
    const today = new Date();
    return today.toISOString().split('T')[0];
  }

  // 필터
  let filters = {
    search: '',
    business_id: null as number | null,
    is_enabled: null as boolean | null,
    date_from: getTodayDate(),
    date_to: ''
  };

  // 수정 모달
  let showEditModal = false;
  let editSchedule: ScheduleWithContext | null = null;
  let editForm = {
    times: '',
    is_enabled: true,
    interval: 10,
    account_id: null as number | null
  };

  // 등록 모달
  let showCreateModal = false;
  let createMode: 'url' | 'select' = 'select';
  let createForm = {
    url: '',
    item_name: '',
    business_name: '',
    business_id: null as number | null,
    item_id: null as number | null,
    date: '',
    times: '',
    is_enabled: true,
    account_id: null as number | null
  };
  let selectedBusinessItems: BizItem[] = [];
  let createLoading = false;

  // 복제 모달
  let showDuplicateModal = false;
  let duplicateSchedule: ScheduleWithContext | null = null;
  let duplicateForm = {
    date: '',
    times: '',
    account_id: null as number | null
  };

  async function fetchSchedules() {
    loading = true;
    error = null;
    try {
      schedules = await scheduleApi.listWithContext({
        search: filters.search || undefined,
        business_id: filters.business_id ?? undefined,
        is_enabled: filters.is_enabled ?? undefined,
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined
      });
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  async function fetchBusinesses() {
    try {
      businesses = await businessApi.list();
    } catch (e) {
      console.error('업체 목록 로드 실패:', e);
    }
  }

  async function fetchAccounts() {
    try {
      accounts = await accountApi.listActive();
    } catch (e) {
      console.error('계정 목록 로드 실패:', e);
    }
  }

  function handleSearch() {
    fetchSchedules();
  }

  function clearFilters() {
    filters = {
      search: '',
      business_id: null,
      is_enabled: null,
      date_from: '',
      date_to: ''
    };
    fetchSchedules();
  }

  async function handleToggleSchedule(schedule: ScheduleWithContext) {
    try {
      if (schedule.is_enabled) {
        await scheduleApi.disable(schedule.id);
      } else {
        await scheduleApi.enable(schedule.id);
      }
      await fetchSchedules();
    } catch (e) {
      alert('상태 변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteSchedule(schedule: ScheduleWithContext) {
    if (!confirm(`${schedule.business_name} - ${schedule.item_name}\n${schedule.date} 일정을 삭제하시겠습니까?`)) return;
    try {
      await scheduleApi.delete(schedule.id);
      await fetchSchedules();
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  function openEditModal(schedule: ScheduleWithContext) {
    editSchedule = schedule;
    editForm = {
      times: schedule.times?.join(', ') || '',
      is_enabled: schedule.is_enabled,
      interval: schedule.interval || 10,
      account_id: schedule.account_id
    };
    showEditModal = true;
  }

  async function handleUpdateSchedule() {
    if (!editSchedule) return;
    try {
      const times = editForm.times ? editForm.times.split(',').map(t => t.trim()).filter(t => t) : [];
      const updateData: MonitorScheduleUpdate = {
        times,
        is_enabled: editForm.is_enabled,
        interval: editForm.interval,
        account_id: editForm.account_id
      };
      await scheduleApi.update(editSchedule.id, updateData);
      showEditModal = false;
      editSchedule = null;
      await fetchSchedules();
    } catch (e) {
      alert('수정 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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

  // 등록 모달 열기
  function openCreateModal() {
    createForm = {
      url: '',
      item_name: '',
      business_name: '',
      business_id: null,
      item_id: null,
      date: '',
      times: '',
      is_enabled: true,
      account_id: null
    };
    selectedBusinessItems = [];
    createMode = 'select';
    showCreateModal = true;
  }

  // 업체 선택 시 아이템 목록 로드
  async function handleBusinessSelect() {
    if (!createForm.business_id) {
      selectedBusinessItems = [];
      createForm.item_id = null;
      return;
    }
    try {
      selectedBusinessItems = await businessApi.getItems(createForm.business_id);
      createForm.item_id = null;
    } catch (e) {
      console.error('아이템 목록 로드 실패:', e);
      selectedBusinessItems = [];
    }
  }

  // URL로 일정 생성
  async function handleCreateFromUrl() {
    if (!createForm.url || !createForm.item_name) {
      alert('URL과 아이템 이름을 입력해주세요.');
      return;
    }
    createLoading = true;
    try {
      const result = await businessApi.importFromUrl({
        url: createForm.url,
        item_name: createForm.item_name,
        business_name: createForm.business_name || undefined,
        auto_booking_enabled: false
      });
      if (result.success) {
        showCreateModal = false;
        await fetchSchedules();
        alert('일정이 등록되었습니다.');
      } else {
        alert(result.message || '등록 실패');
      }
    } catch (e) {
      alert('등록 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    } finally {
      createLoading = false;
    }
  }

  // 아이템 선택으로 일정 생성
  async function handleCreateFromSelect() {
    if (!createForm.item_id || !createForm.date) {
      alert('아이템과 날짜를 선택해주세요.');
      return;
    }
    createLoading = true;
    try {
      const times = createForm.times ? createForm.times.split(',').map(t => t.trim()).filter(t => t) : [];
      const scheduleData: MonitorScheduleCreate = {
        date: createForm.date,
        times,
        is_enabled: createForm.is_enabled,
        account_id: createForm.account_id
      };
      await itemApi.createSchedule(createForm.item_id, scheduleData);
      showCreateModal = false;
      await fetchSchedules();
      alert('일정이 등록되었습니다.');
    } catch (e) {
      alert('등록 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    } finally {
      createLoading = false;
    }
  }

  // 복제 모달 열기
  function openDuplicateModal(schedule: ScheduleWithContext) {
    duplicateSchedule = schedule;
    duplicateForm = {
      date: schedule.date,
      times: schedule.times?.join(', ') || '',
      account_id: schedule.account_id
    };
    showDuplicateModal = true;
  }

  // 일정 복제
  async function handleDuplicate() {
    if (!duplicateSchedule || !duplicateForm.date) {
      alert('날짜를 입력해주세요.');
      return;
    }
    try {
      const times = duplicateForm.times ? duplicateForm.times.split(',').map(t => t.trim()).filter(t => t) : [];
      const scheduleData: MonitorScheduleCreate = {
        date: duplicateForm.date,
        times,
        is_enabled: true,
        account_id: duplicateForm.account_id
      };
      await itemApi.createSchedule(duplicateSchedule.biz_item_pk, scheduleData);
      showDuplicateModal = false;
      duplicateSchedule = null;
      await fetchSchedules();
    } catch (e) {
      alert('복제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  function formatDate(dateStr: string) {
    const date = new Date(dateStr);
    const today = new Date();
    const diffDays = Math.ceil((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));

    let badge = '';
    if (diffDays < 0) {
      badge = '지남';
    } else if (diffDays === 0) {
      badge = '오늘';
    } else if (diffDays === 1) {
      badge = '내일';
    } else if (diffDays <= 7) {
      badge = `D-${diffDays}`;
    }

    return { date: dateStr, badge };
  }

  onMount(() => {
    fetchSchedules();
    fetchBusinesses();
    fetchAccounts();
  });
</script>

<div class="p-6">
  <div class="mb-6 flex justify-between items-center">
    <h2 class="text-2xl font-bold text-gray-900">일정 관리</h2>
    <div class="flex gap-2">
      <button class="btn btn-primary btn-sm" on:click={openCreateModal}>
        일정 등록
      </button>
      <button class="btn btn-secondary btn-sm" on:click={fetchSchedules}>
        새로고침
      </button>
    </div>
  </div>

  <!-- 필터 영역 -->
  <div class="card mb-6">
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
      <div>
        <label for="search" class="block text-sm font-medium text-gray-700 mb-1">검색</label>
        <input
          id="search"
          type="text"
          class="input"
          placeholder="업체명/아이템명"
          bind:value={filters.search}
          on:keydown={(e) => e.key === 'Enter' && handleSearch()}
        />
      </div>
      <div>
        <label for="business" class="block text-sm font-medium text-gray-700 mb-1">업체</label>
        <select id="business" class="input" bind:value={filters.business_id}>
          <option value={null}>전체</option>
          {#each businesses as business}
            <option value={business.id}>{business.name}</option>
          {/each}
        </select>
      </div>
      <div>
        <label for="status" class="block text-sm font-medium text-gray-700 mb-1">상태</label>
        <select id="status" class="input" bind:value={filters.is_enabled}>
          <option value={null}>전체</option>
          <option value={true}>활성</option>
          <option value={false}>비활성</option>
        </select>
      </div>
      <div>
        <label for="date_from" class="block text-sm font-medium text-gray-700 mb-1">시작일</label>
        <input id="date_from" type="date" class="input" bind:value={filters.date_from} />
      </div>
      <div>
        <label for="date_to" class="block text-sm font-medium text-gray-700 mb-1">종료일</label>
        <input id="date_to" type="date" class="input" bind:value={filters.date_to} />
      </div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" on:click={handleSearch}>검색</button>
      <button class="btn btn-secondary" on:click={clearFilters}>초기화</button>
    </div>
  </div>

  <!-- 일정 목록 -->
  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else if schedules.length === 0}
    <div class="card text-center py-12">
      <p class="text-gray-500">등록된 일정이 없습니다.</p>
    </div>
  {:else}
    <div class="card">
      <div class="mb-4 text-sm text-gray-600">
        총 {schedules.length}개의 일정
      </div>
      <div class="overflow-x-auto">
        <table class="table">
          <thead>
            <tr>
              <th>날짜</th>
              <th>업체</th>
              <th>아이템</th>
              <th>시간</th>
              <th>계정</th>
              <th>상태</th>
              <th>예약</th>
              <th class="w-32">작업</th>
            </tr>
          </thead>
          <tbody>
            {#each schedules as schedule (schedule.id)}
              {@const status = getStatusBadge(schedule.run_status, schedule.is_enabled)}
              {@const dateInfo = formatDate(schedule.date)}
              <tr class="{!schedule.is_enabled ? 'opacity-60' : ''} {schedule.error_count > 0 ? 'bg-red-50' : ''}">
                <td
                  class="cursor-pointer hover:bg-gray-100"
                  on:click={() => handleToggleSchedule(schedule)}
                  title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                >
                  <div class="flex items-center gap-2">
                    <span class="font-medium">{dateInfo.date}</span>
                    {#if dateInfo.badge}
                      <span class="badge {dateInfo.badge === '지남' ? 'badge-gray' : dateInfo.badge === '오늘' ? 'badge-warning' : 'badge-info'}">{dateInfo.badge}</span>
                    {/if}
                  </div>
                </td>
                <td
                  class="cursor-pointer hover:bg-gray-100"
                  on:click={() => handleToggleSchedule(schedule)}
                  title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                >
                  <div class="flex items-center gap-2">
                    <span>{schedule.business_name}</span>
                    {#if !schedule.business_is_enabled}
                      <span class="badge badge-gray text-xs">비활성</span>
                    {/if}
                  </div>
                </td>
                <td
                  class="cursor-pointer hover:bg-gray-100"
                  on:click={() => handleToggleSchedule(schedule)}
                  title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                >
                  <div class="flex items-center gap-2">
                    <span>{schedule.item_name}</span>
                    {#if schedule.auto_booking_enabled}
                      <span class="badge badge-success text-xs">자동예약</span>
                    {/if}
                    {#if !schedule.item_is_enabled}
                      <span class="badge badge-gray text-xs">비활성</span>
                    {/if}
                  </div>
                </td>
                <td
                  class="cursor-pointer hover:bg-gray-100"
                  on:click={() => handleToggleSchedule(schedule)}
                  title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                >
                  {#if schedule.times && schedule.times.length > 0}
                    <div class="text-sm">
                      {#if schedule.times.length <= 3}
                        {schedule.times.join(', ')}
                      {:else}
                        {schedule.times.slice(0, 3).join(', ')}
                        <span class="text-gray-400">외 {schedule.times.length - 3}개</span>
                      {/if}
                    </div>
                  {:else if schedule.time_range}
                    <span class="text-gray-500">{schedule.time_range}</span>
                  {:else}
                    <span class="text-gray-400">-</span>
                  {/if}
                </td>
                <td
                  class="cursor-pointer hover:bg-gray-100"
                  on:click={() => handleToggleSchedule(schedule)}
                  title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                >
                  {#if schedule.account_name}
                    <span class="badge badge-info">{schedule.account_name}</span>
                  {:else}
                    <span class="text-gray-400">기본</span>
                  {/if}
                </td>
                <td
                  class="cursor-pointer hover:bg-gray-100"
                  on:click={() => handleToggleSchedule(schedule)}
                  title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                >
                  <span class="badge {status.class}">{status.text}</span>
                  {#if schedule.error_count > 0}
                    <span class="text-xs text-red-600 block" title={schedule.last_error || ''}>
                      오류 {schedule.error_count}회
                    </span>
                  {/if}
                </td>
                <td>
                  {#if schedule.booking_count > 0}
                    <span class="text-green-600 font-medium">{schedule.booking_count}건</span>
                  {:else}
                    <span class="text-gray-400">-</span>
                  {/if}
                </td>
                <td>
                  <div class="flex gap-1">
                    <button
                      class="btn btn-secondary btn-xs"
                      on:click={() => openEditModal(schedule)}
                      title="수정"
                    >
                      수정
                    </button>
                    <button
                      class="btn btn-secondary btn-xs"
                      on:click={() => openDuplicateModal(schedule)}
                      title="복제"
                    >
                      복제
                    </button>
                    <button
                      class="btn btn-danger btn-xs"
                      on:click={() => handleDeleteSchedule(schedule)}
                      title="삭제"
                    >
                      삭제
                    </button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>

<!-- 수정 모달 -->
{#if showEditModal && editSchedule}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">일정 수정</h3>
        <p class="text-sm text-gray-500 mt-1">
          {editSchedule.business_name} - {editSchedule.item_name} ({editSchedule.date})
        </p>
      </div>
      <form on:submit|preventDefault={handleUpdateSchedule} class="p-4 space-y-4">
        <div>
          <label for="edit-times" class="block text-sm font-medium text-gray-700 mb-1">시간 (쉼표 구분)</label>
          <input
            id="edit-times"
            type="text"
            class="input"
            bind:value={editForm.times}
            placeholder="예: 10:00, 14:00, 18:00"
          />
          <p class="text-xs text-gray-500 mt-1">비워두면 시간 범위 설정을 따릅니다</p>
        </div>
        <div>
          <label for="edit-interval" class="block text-sm font-medium text-gray-700 mb-1">모니터링 간격 (초)</label>
          <input
            id="edit-interval"
            type="number"
            class="input"
            bind:value={editForm.interval}
            min="1"
            max="300"
          />
        </div>
        <div>
          <label for="edit-account" class="block text-sm font-medium text-gray-700 mb-1">사용 계정</label>
          <select id="edit-account" class="input" bind:value={editForm.account_id}>
            <option value={null}>기본 계정</option>
            {#each accounts as account}
              <option value={account.id}>{account.name}</option>
            {/each}
          </select>
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={editForm.is_enabled} />
          <span class="text-sm font-medium text-gray-700">활성화</span>
        </label>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" on:click={() => { showEditModal = false; editSchedule = null; }}>
            취소
          </button>
          <button type="submit" class="btn btn-primary">저장</button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 등록 모달 -->
{#if showCreateModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">일정 등록</h3>
        <div class="flex gap-2 mt-3">
          <button
            class="px-3 py-1 text-sm rounded-md {createMode === 'select' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700'}"
            on:click={() => createMode = 'select'}
          >
            업체/아이템 선택
          </button>
          <button
            class="px-3 py-1 text-sm rounded-md {createMode === 'url' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700'}"
            on:click={() => createMode = 'url'}
          >
            URL로 등록
          </button>
        </div>
      </div>

      {#if createMode === 'select'}
        <form on:submit|preventDefault={handleCreateFromSelect} class="p-4 space-y-4">
          <div>
            <label for="create-business" class="block text-sm font-medium text-gray-700 mb-1">업체</label>
            <select
              id="create-business"
              class="input"
              bind:value={createForm.business_id}
              on:change={handleBusinessSelect}
            >
              <option value={null}>업체 선택</option>
              {#each businesses as business}
                <option value={business.id}>{business.name}</option>
              {/each}
            </select>
          </div>
          <div>
            <label for="create-item" class="block text-sm font-medium text-gray-700 mb-1">아이템</label>
            <select id="create-item" class="input" bind:value={createForm.item_id} disabled={!createForm.business_id}>
              <option value={null}>아이템 선택</option>
              {#each selectedBusinessItems as item}
                <option value={item.id}>{item.name}</option>
              {/each}
            </select>
          </div>
          <div>
            <label for="create-date" class="block text-sm font-medium text-gray-700 mb-1">날짜</label>
            <input id="create-date" type="date" class="input" bind:value={createForm.date} />
          </div>
          <div>
            <label for="create-times" class="block text-sm font-medium text-gray-700 mb-1">시간 (쉼표 구분, 선택)</label>
            <input
              id="create-times"
              type="text"
              class="input"
              bind:value={createForm.times}
              placeholder="예: 10:00, 14:00, 18:00"
            />
            <p class="text-xs text-gray-500 mt-1">비워두면 아이템의 시간 범위 설정을 따릅니다</p>
          </div>
          <div>
            <label for="create-account" class="block text-sm font-medium text-gray-700 mb-1">사용 계정</label>
            <select id="create-account" class="input" bind:value={createForm.account_id}>
              <option value={null}>기본 계정</option>
              {#each accounts as account}
                <option value={account.id}>{account.name}</option>
              {/each}
            </select>
          </div>
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={createForm.is_enabled} />
            <span class="text-sm font-medium text-gray-700">활성화</span>
          </label>
          <div class="flex justify-end gap-2 pt-4">
            <button type="button" class="btn btn-secondary" on:click={() => showCreateModal = false}>
              취소
            </button>
            <button type="submit" class="btn btn-primary" disabled={createLoading}>
              {createLoading ? '등록 중...' : '등록'}
            </button>
          </div>
        </form>
      {:else}
        <form on:submit|preventDefault={handleCreateFromUrl} class="p-4 space-y-4">
          <div>
            <label for="create-url" class="block text-sm font-medium text-gray-700 mb-1">네이버 예약 URL</label>
            <input
              id="create-url"
              type="url"
              class="input"
              bind:value={createForm.url}
              placeholder="https://booking.naver.com/booking/..."
            />
          </div>
          <div>
            <label for="create-item-name" class="block text-sm font-medium text-gray-700 mb-1">아이템 이름</label>
            <input
              id="create-item-name"
              type="text"
              class="input"
              bind:value={createForm.item_name}
              placeholder="예: 프라이빗 사우나 A"
            />
          </div>
          <div>
            <label for="create-business-name" class="block text-sm font-medium text-gray-700 mb-1">업체 이름 (선택)</label>
            <input
              id="create-business-name"
              type="text"
              class="input"
              bind:value={createForm.business_name}
              placeholder="자동으로 가져옵니다"
            />
            <p class="text-xs text-gray-500 mt-1">비워두면 URL에서 자동으로 가져옵니다</p>
          </div>
          <div class="flex justify-end gap-2 pt-4">
            <button type="button" class="btn btn-secondary" on:click={() => showCreateModal = false}>
              취소
            </button>
            <button type="submit" class="btn btn-primary" disabled={createLoading}>
              {createLoading ? '등록 중...' : '등록'}
            </button>
          </div>
        </form>
      {/if}
    </div>
  </div>
{/if}

<!-- 복제 모달 -->
{#if showDuplicateModal && duplicateSchedule}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">일정 복제</h3>
        <p class="text-sm text-gray-500 mt-1">
          {duplicateSchedule.business_name} - {duplicateSchedule.item_name}
        </p>
      </div>
      <form on:submit|preventDefault={handleDuplicate} class="p-4 space-y-4">
        <div>
          <label for="dup-date" class="block text-sm font-medium text-gray-700 mb-1">날짜</label>
          <input id="dup-date" type="date" class="input" bind:value={duplicateForm.date} />
        </div>
        <div>
          <label for="dup-times" class="block text-sm font-medium text-gray-700 mb-1">시간 (쉼표 구분)</label>
          <input
            id="dup-times"
            type="text"
            class="input"
            bind:value={duplicateForm.times}
            placeholder="예: 10:00, 14:00, 18:00"
          />
          <p class="text-xs text-gray-500 mt-1">비워두면 아이템의 시간 범위 설정을 따릅니다</p>
        </div>
        <div>
          <label for="dup-account" class="block text-sm font-medium text-gray-700 mb-1">사용 계정</label>
          <select id="dup-account" class="input" bind:value={duplicateForm.account_id}>
            <option value={null}>기본 계정</option>
            {#each accounts as account}
              <option value={account.id}>{account.name}</option>
            {/each}
          </select>
        </div>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" on:click={() => { showDuplicateModal = false; duplicateSchedule = null; }}>
            취소
          </button>
          <button type="submit" class="btn btn-primary">복제</button>
        </div>
      </form>
    </div>
  </div>
{/if}

<style>
  .badge {
    display: inline-block;
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
  .table {
    width: 100%;
    border-collapse: collapse;
  }
  .table th, .table td {
    padding: 0.75rem;
    text-align: left;
    border-bottom: 1px solid #e5e7eb;
  }
  .table th {
    font-weight: 600;
    font-size: 0.875rem;
    color: #374151;
    background-color: #f9fafb;
  }
  .table tbody tr:hover {
    background-color: #f9fafb;
  }
  .btn-xs {
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
  }
</style>
