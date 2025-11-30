<script lang="ts">
  import { onMount } from 'svelte';
  import { targetsApi, bulkApi } from '$lib/api';
  import type { MonitorTarget } from '$lib/types';

  let targets: MonitorTarget[] = [];
  let loading = true;
  let error: string | null = null;
  let selectedIds: Set<number> = new Set();
  let showAddModal = false;
  let editingTarget: MonitorTarget | null = null;

  // 필터
  let filterServiceType = '';
  let filterStatus = '';
  let searchQuery = '';

  // 날짜 범위 필터 (기본값: 오늘부터)
  let filterDateStart: string = new Date().toISOString().split('T')[0];
  let filterDateEnd: string = '';

  // 새 대상 폼
  let newTarget = {
    url: '',
    label: '',
    category: 'default',
    service_type: 'naver',
    auto_booking_enabled: false,
    time_range: ''
  };

  async function fetchTargets() {
    loading = true;
    try {
      const filters: { service_type?: string } = {};
      if (filterServiceType) filters.service_type = filterServiceType;
      targets = await targetsApi.list(filters);
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  function getStatusBadge(target: MonitorTarget) {
    if (!target.is_enabled) return { class: 'badge-gray', text: '비활성' };
    switch (target.run_status) {
      case 'running': return { class: 'badge-success', text: '실행 중' };
      case 'queued': return { class: 'badge-info', text: '대기 중' };
      case 'error': return { class: 'badge-error', text: '오류' };
      case 'paused': return { class: 'badge-warning', text: '일시 중지' };
      default: return { class: 'badge-gray', text: '대기' };
    }
  }

  function filteredTargets() {
    return targets.filter(t => {
      // 상태 필터
      if (filterStatus) {
        if (filterStatus === 'running' && t.run_status !== 'running') return false;
        if (filterStatus === 'error' && t.run_status !== 'error') return false;
        if (filterStatus === 'disabled' && t.is_enabled) return false;
      }
      // 검색어 필터
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        if (!t.label.toLowerCase().includes(q) && !t.url.toLowerCase().includes(q)) {
          return false;
        }
      }
      // 날짜 범위 필터
      if (t.date) {
        const targetDate = t.date;
        if (filterDateStart && targetDate < filterDateStart) return false;
        if (filterDateEnd && targetDate > filterDateEnd) return false;
      }
      return true;
    });
  }

  function toggleSelect(id: number) {
    if (selectedIds.has(id)) {
      selectedIds.delete(id);
    } else {
      selectedIds.add(id);
    }
    selectedIds = selectedIds;
  }

  function toggleSelectAll() {
    const filtered = filteredTargets();
    if (selectedIds.size === filtered.length) {
      selectedIds.clear();
    } else {
      filtered.forEach(t => selectedIds.add(t.id));
    }
    selectedIds = selectedIds;
  }

  async function handleCreate() {
    try {
      await targetsApi.create({
        url: newTarget.url,
        label: newTarget.label,
        category: newTarget.category,
        service_type: newTarget.service_type
      });
      showAddModal = false;
      newTarget = { url: '', label: '', category: 'default', service_type: 'naver', auto_booking_enabled: false, time_range: '' };
      await fetchTargets();
    } catch (e) {
      alert('생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleUpdate() {
    if (!editingTarget) return;
    try {
      await targetsApi.update(editingTarget.id, {
        label: editingTarget.label,
        category: editingTarget.category,
        is_enabled: editingTarget.is_enabled,
        auto_booking_enabled: editingTarget.auto_booking_enabled,
        max_bookings: editingTarget.max_bookings,
        time_range: editingTarget.time_range || undefined
      });
      editingTarget = null;
      await fetchTargets();
    } catch (e) {
      alert('수정 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDelete(id: number) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
      await targetsApi.delete(id);
      await fetchTargets();
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleStart(id: number) {
    try {
      await targetsApi.start(id);
      await fetchTargets();
    } catch (e) {
      alert('시작 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleStop(id: number) {
    try {
      await targetsApi.stop(id);
      await fetchTargets();
    } catch (e) {
      alert('중지 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleBulkStart() {
    if (selectedIds.size === 0) return;
    try {
      await bulkApi.start({ target_ids: Array.from(selectedIds) });
      selectedIds.clear();
      selectedIds = selectedIds;
      await fetchTargets();
    } catch (e) {
      alert('일괄 시작 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleBulkStop() {
    if (selectedIds.size === 0) return;
    try {
      await bulkApi.stop({ target_ids: Array.from(selectedIds) });
      selectedIds.clear();
      selectedIds = selectedIds;
      await fetchTargets();
    } catch (e) {
      alert('일괄 중지 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleBulkDelete() {
    if (selectedIds.size === 0) return;
    if (!confirm(`${selectedIds.size}개 대상을 삭제하시겠습니까?`)) return;
    try {
      await bulkApi.delete(Array.from(selectedIds));
      selectedIds.clear();
      selectedIds = selectedIds;
      await fetchTargets();
    } catch (e) {
      alert('일괄 삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  function clearDateFilter() {
    filterDateStart = '';
    filterDateEnd = '';
  }

  function setTodayFilter() {
    filterDateStart = new Date().toISOString().split('T')[0];
    filterDateEnd = '';
  }

  onMount(fetchTargets);
</script>

<div class="p-6">
  <div class="mb-6 flex justify-between items-center">
    <h2 class="text-2xl font-bold text-gray-900">모니터링 대상</h2>
    <button class="btn btn-primary" on:click={() => showAddModal = true}>
      + 새 대상 추가
    </button>
  </div>

  <!-- 필터 및 검색 -->
  <div class="card mb-4">
    <div class="flex flex-wrap gap-4 items-end">
      <div>
        <label class="block text-xs text-gray-500 mb-1">검색</label>
        <input
          type="text"
          class="input"
          style="width: 180px;"
          placeholder="라벨 또는 URL..."
          bind:value={searchQuery}
        />
      </div>
      <div>
        <label class="block text-xs text-gray-500 mb-1">서비스</label>
        <select class="input" style="width: 120px;" bind:value={filterServiceType} on:change={fetchTargets}>
          <option value="">전체</option>
          <option value="naver">네이버</option>
          <option value="coupang">쿠팡</option>
        </select>
      </div>
      <div>
        <label class="block text-xs text-gray-500 mb-1">상태</label>
        <select class="input" style="width: 120px;" bind:value={filterStatus}>
          <option value="">전체</option>
          <option value="running">실행 중</option>
          <option value="error">오류</option>
          <option value="disabled">비활성</option>
        </select>
      </div>
      <div>
        <label class="block text-xs text-gray-500 mb-1">날짜 시작</label>
        <input
          type="date"
          class="input"
          style="width: 150px;"
          bind:value={filterDateStart}
        />
      </div>
      <div>
        <label class="block text-xs text-gray-500 mb-1">날짜 끝</label>
        <input
          type="date"
          class="input"
          style="width: 150px;"
          bind:value={filterDateEnd}
        />
      </div>
      <div class="flex gap-1">
        <button class="btn btn-secondary btn-sm" on:click={setTodayFilter} title="오늘부터">
          오늘~
        </button>
        <button class="btn btn-secondary btn-sm" on:click={clearDateFilter} title="날짜 필터 해제">
          X
        </button>
      </div>
      <button class="btn btn-secondary btn-sm" on:click={fetchTargets}>
        새로고침
      </button>
    </div>
  </div>

  <!-- 일괄 작업 -->
  {#if selectedIds.size > 0}
    <div class="card mb-4 bg-blue-50 border-blue-200">
      <div class="flex items-center gap-4">
        <span class="text-blue-800 font-medium">{selectedIds.size}개 선택됨</span>
        <button class="btn btn-success btn-sm" on:click={handleBulkStart}>일괄 시작</button>
        <button class="btn btn-secondary btn-sm" on:click={handleBulkStop}>일괄 중지</button>
        <button class="btn btn-danger btn-sm" on:click={handleBulkDelete}>일괄 삭제</button>
        <button class="btn btn-secondary btn-sm" on:click={() => { selectedIds.clear(); selectedIds = selectedIds; }}>
          선택 해제
        </button>
      </div>
    </div>
  {/if}

  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else}
    <div class="card overflow-x-auto">
      <table class="table">
        <thead>
          <tr>
            <th class="w-10">
              <input
                type="checkbox"
                checked={selectedIds.size === filteredTargets().length && filteredTargets().length > 0}
                on:change={toggleSelectAll}
              />
            </th>
            <th>라벨</th>
            <th>날짜</th>
            <th>URL</th>
            <th>서비스</th>
            <th>상태</th>
            <th>예약</th>
            <th>마지막 확인</th>
            <th class="w-40">작업</th>
          </tr>
        </thead>
        <tbody>
          {#each filteredTargets() as target (target.id)}
            {@const status = getStatusBadge(target)}
            {@const isDisabled = !target.is_enabled}
            <tr class={isDisabled ? 'opacity-50 bg-gray-50' : ''}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedIds.has(target.id)}
                  on:change={() => toggleSelect(target.id)}
                />
              </td>
              <td class="font-medium {isDisabled ? 'text-gray-400' : ''}">{target.label}</td>
              <td class="text-sm {isDisabled ? 'text-gray-400' : 'text-gray-600'}">
                {target.date || '-'}
              </td>
              <td class="max-w-xs truncate text-sm {isDisabled ? 'text-gray-400' : 'text-gray-500'}" title={target.url}>
                {target.url}
              </td>
              <td>
                <span class="badge {isDisabled ? 'badge-gray' : 'badge-info'}">{target.service_type}</span>
              </td>
              <td>
                <span class="badge {status.class}">{status.text}</span>
              </td>
              <td>
                {#if target.auto_booking_enabled}
                  <span class="badge {isDisabled ? 'badge-gray' : 'badge-success'}">
                    {target.booking_count}/{target.max_bookings}
                  </span>
                {:else}
                  <span class="text-gray-400">-</span>
                {/if}
              </td>
              <td class="text-sm {isDisabled ? 'text-gray-400' : 'text-gray-500'}">
                {#if target.last_check}
                  {new Date(target.last_check).toLocaleString('ko-KR')}
                {:else}
                  -
                {/if}
              </td>
              <td>
                <div class="flex gap-1">
                  {#if target.run_status === 'running'}
                    <button class="btn btn-secondary btn-sm" on:click={() => handleStop(target.id)} title="중지">
                      ⏹
                    </button>
                  {:else}
                    <button class="btn btn-success btn-sm" on:click={() => handleStart(target.id)} title="시작" disabled={isDisabled}>
                      ▶
                    </button>
                  {/if}
                  <button class="btn btn-secondary btn-sm" on:click={() => editingTarget = {...target}} title="수정">
                    ✏
                  </button>
                  <button class="btn btn-danger btn-sm" on:click={() => handleDelete(target.id)} title="삭제">
                    🗑
                  </button>
                </div>
              </td>
            </tr>
          {:else}
            <tr>
              <td colspan="9" class="text-center text-gray-500 py-8">
                모니터링 대상이 없습니다.
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="mt-2 text-sm text-gray-500">
        총 {filteredTargets().length}개 / 전체 {targets.length}개
      </div>
    </div>
  {/if}
</div>

<!-- 추가 모달 -->
{#if showAddModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">새 모니터링 대상 추가</h3>
      </div>
      <form on:submit|preventDefault={handleCreate} class="p-4 space-y-4">
        <div>
          <label for="new-url" class="block text-sm font-medium text-gray-700 mb-1">URL</label>
          <input id="new-url" type="url" class="input" bind:value={newTarget.url} required placeholder="https://booking.naver.com/..." />
        </div>
        <div>
          <label for="new-label" class="block text-sm font-medium text-gray-700 mb-1">라벨</label>
          <input id="new-label" type="text" class="input" bind:value={newTarget.label} required placeholder="표시 이름" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="new-service" class="block text-sm font-medium text-gray-700 mb-1">서비스</label>
            <select id="new-service" class="input" bind:value={newTarget.service_type}>
              <option value="naver">네이버</option>
              <option value="coupang">쿠팡</option>
            </select>
          </div>
          <div>
            <label for="new-category" class="block text-sm font-medium text-gray-700 mb-1">카테고리</label>
            <input id="new-category" type="text" class="input" bind:value={newTarget.category} placeholder="default" />
          </div>
        </div>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" on:click={() => showAddModal = false}>
            취소
          </button>
          <button type="submit" class="btn btn-primary">추가</button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 수정 모달 -->
{#if editingTarget}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">대상 수정</h3>
      </div>
      <form on:submit|preventDefault={handleUpdate} class="p-4 space-y-4">
        <div>
          <label for="edit-label" class="block text-sm font-medium text-gray-700 mb-1">라벨</label>
          <input id="edit-label" type="text" class="input" bind:value={editingTarget.label} required />
        </div>
        <div>
          <label for="edit-category" class="block text-sm font-medium text-gray-700 mb-1">카테고리</label>
          <input id="edit-category" type="text" class="input" bind:value={editingTarget.category} />
        </div>
        <div class="flex items-center gap-2">
          <input type="checkbox" id="is_enabled" bind:checked={editingTarget.is_enabled} />
          <label for="is_enabled" class="text-sm font-medium text-gray-700">활성화</label>
        </div>
        <hr />
        <div class="flex items-center gap-2">
          <input type="checkbox" id="auto_booking" bind:checked={editingTarget.auto_booking_enabled} />
          <label for="auto_booking" class="text-sm font-medium text-gray-700">자동 예약</label>
        </div>
        {#if editingTarget.auto_booking_enabled}
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label for="edit-max-bookings" class="block text-sm font-medium text-gray-700 mb-1">최대 예약 수</label>
              <input id="edit-max-bookings" type="number" class="input" bind:value={editingTarget.max_bookings} min="1" />
            </div>
            <div>
              <label for="edit-time-range" class="block text-sm font-medium text-gray-700 mb-1">시간 범위</label>
              <input id="edit-time-range" type="text" class="input" bind:value={editingTarget.time_range} placeholder="18:00-21:00" />
            </div>
          </div>
        {/if}
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" on:click={() => editingTarget = null}>
            취소
          </button>
          <button type="submit" class="btn btn-primary">저장</button>
        </div>
      </form>
    </div>
  </div>
{/if}
