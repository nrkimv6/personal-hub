<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import CoupangMonitoringHistory from '$lib/components/CoupangMonitoringHistory.svelte';
  import {
    coupangTravelApi,
    type CoupangTarget,
    type CoupangSchedule,
    type CoupangStatusSummary
  } from '$lib/api/coupangTravel';
  import { serviceAccountApi, type ServiceAccountWithProfile } from '$lib/api/common';
  import { createSelection } from '$lib/utils/selection.svelte';
  import { toast } from '$lib/stores/toast';

  let targets = $state<CoupangTarget[]>([]);
  let schedules = $state<CoupangSchedule[]>([]);
  let accounts = $state<ServiceAccountWithProfile[]>([]);
  let statusSummary = $state<CoupangStatusSummary>({
    total_schedules: 0,
    enabled_schedules: 0,
    active_schedules: 0
  });

  let loading = $state(false);
  let error = $state('');
  let activeTab = $state<'schedules' | 'history'>('schedules');

  let newUrl = $state('');
  let newVendorItemPackageId = $state('');
  let newName = $state('');
  let submittingTarget = $state(false);

  let selectedTargetId = $state('');
  let newDate = $state('');
  let selectedAccountId = $state('');
  let newTimes = $state('');
  let submittingSchedule = $state(false);

  let scheduleFilters = $state({
    search: '',
    is_enabled: 'all' as 'all' | 'enabled' | 'disabled',
    date_from: getTodayDate(),
    date_to: ''
  });

  let refreshInterval: ReturnType<typeof setInterval> | null = null;
  let loadAllController: AbortController | null = null;
  let pollingController: AbortController | null = null;

  const selection = createSelection();

  const coupangTabs = $derived([
    { id: 'schedules', label: '일정', count: schedules.length || undefined },
    { id: 'history', label: '이력' }
  ]);

  const filteredSchedules = $derived(
    schedules.filter((schedule) => {
      const query = scheduleFilters.search.trim().toLowerCase();
      if (query) {
        const text = `${schedule.item_name ?? ''} ${schedule.business_name ?? ''} ${schedule.product_id ?? ''}`.toLowerCase();
        if (!text.includes(query)) return false;
      }
      if (scheduleFilters.is_enabled === 'enabled' && !schedule.is_enabled) return false;
      if (scheduleFilters.is_enabled === 'disabled' && schedule.is_enabled) return false;
      if (scheduleFilters.date_from && schedule.date < scheduleFilters.date_from) return false;
      if (scheduleFilters.date_to && schedule.date > scheduleFilters.date_to) return false;
      return true;
    })
  );

  async function loadAll(showLoading = true): Promise<void> {
    if (showLoading) loading = true;
    loadAllController?.abort();
    loadAllController = new AbortController();
    error = '';

    try {
      const [targetData, scheduleData, accountData, statusData] = await Promise.all([
        coupangTravelApi.listTargets({ signal: loadAllController.signal }),
        coupangTravelApi.listSchedules({ signal: loadAllController.signal }),
        serviceAccountApi.listActive('coupang', { signal: loadAllController.signal }),
        coupangTravelApi.getStatus({ signal: loadAllController.signal })
      ]);
      targets = targetData;
      schedules = scheduleData;
      accounts = accountData;
      statusSummary = statusData;
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') return;
      const message = e instanceof Error ? e.message : '쿠팡 데이터 로드 실패';
      error = message;
    } finally {
      if (showLoading) loading = false;
    }
  }

  async function fetchSchedulesAndStatus(showLoading = false): Promise<void> {
    if (showLoading) loading = true;
    pollingController?.abort();
    pollingController = new AbortController();

    try {
      const [scheduleData, statusData] = await Promise.all([
        coupangTravelApi.listSchedules({ signal: pollingController.signal }),
        coupangTravelApi.getStatus({ signal: pollingController.signal })
      ]);
      schedules = scheduleData;
      statusSummary = statusData;
      error = '';
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') return;
      const message = e instanceof Error ? e.message : '쿠팡 일정 갱신 실패';
      error = message;
    } finally {
      if (showLoading) loading = false;
    }
  }

  function getTodayDate(): string {
    return new Date().toISOString().split('T')[0];
  }

  function clearMessages(): void {
    error = '';
  }

  function cleanupPolling(): void {
    if (refreshInterval) {
      clearInterval(refreshInterval);
      refreshInterval = null;
    }
    loadAllController?.abort();
    loadAllController = null;
    pollingController?.abort();
    pollingController = null;
  }

  async function submitTarget(): Promise<void> {
    if (!newUrl.trim() || !newVendorItemPackageId.trim() || !newName.trim()) {
      toast.error('URL, vendor_item_package_id, 이름을 모두 입력해주세요.');
      return;
    }

    submittingTarget = true;
    try {
      await coupangTravelApi.createTarget({
        url: newUrl.trim(),
        vendor_item_package_id: newVendorItemPackageId.trim(),
        name: newName.trim()
      });
      newUrl = '';
      newVendorItemPackageId = '';
      newName = '';
      toast.success('상품이 등록되었습니다.');
      await loadAll(false);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '상품 등록 실패');
    } finally {
      submittingTarget = false;
    }
  }

  async function deleteTarget(id: number): Promise<void> {
    try {
      await coupangTravelApi.deleteTarget(id);
      toast.success('상품이 삭제되었습니다.');
      await loadAll(false);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '상품 삭제 실패');
    }
  }

  async function submitSchedule(): Promise<void> {
    const targetId = Number(selectedTargetId);
    const accountId = Number(selectedAccountId);

    if (!targetId || !newDate) {
      toast.error('상품과 날짜를 선택해주세요.');
      return;
    }

    submittingSchedule = true;
    try {
      const scheduleBody: { biz_item_id: number; dates: string[]; service_account_id?: number; times?: string[] } = {
        biz_item_id: targetId,
        dates: [newDate]
      };
      if (accountId) {
        scheduleBody.service_account_id = accountId;
      }
      const parsedTimes = newTimes.trim()
        ? newTimes.split(',').map((t) => t.trim()).filter(Boolean)
        : undefined;
      if (parsedTimes) {
        scheduleBody.times = parsedTimes;
      }
      const result = await coupangTravelApi.createSchedules(scheduleBody);
      newDate = '';
      newTimes = '';
      toast.success(`일정 ${result.created}건이 추가되었습니다.`);
      await fetchSchedulesAndStatus(false);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '일정 등록 실패');
    } finally {
      submittingSchedule = false;
    }
  }

  async function toggleSchedule(schedule: CoupangSchedule): Promise<void> {
    try {
      if (schedule.is_enabled) {
        await coupangTravelApi.disableSchedule(schedule.id);
      } else {
        await coupangTravelApi.enableSchedule(schedule.id);
      }
      await fetchSchedulesAndStatus(false);
      toast.success(`일정이 ${schedule.is_enabled ? '비활성화' : '활성화'}되었습니다.`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '일정 상태 변경 실패');
    }
  }

  async function deleteSchedule(id: number): Promise<void> {
    try {
      await coupangTravelApi.deleteSchedule(id);
      selection.clear();
      toast.success('일정이 삭제되었습니다.');
      await fetchSchedulesAndStatus(false);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '일정 삭제 실패');
    }
  }

  async function runBulkAction(action: 'enable' | 'disable' | 'delete'): Promise<void> {
    const ids = selection.toArray();
    if (ids.length === 0) return;

    const results = await Promise.allSettled(
      ids.map(async (id) => {
        if (action === 'enable') return coupangTravelApi.enableSchedule(id);
        if (action === 'disable') return coupangTravelApi.disableSchedule(id);
        return coupangTravelApi.deleteSchedule(id);
      })
    );

    const successCount = results.filter((r) => r.status === 'fulfilled').length;
    const failedCount = results.length - successCount;
    selection.clear();

    await fetchSchedulesAndStatus(false);

    const actionLabel =
      action === 'enable' ? '활성화' : action === 'disable' ? '비활성화' : '삭제';

    if (failedCount > 0) {
      toast.warning(`일괄 ${actionLabel}: ${successCount}건 성공, ${failedCount}건 실패`);
      return;
    }
    toast.success(`일괄 ${actionLabel} 완료 (${successCount}건)`);
  }

  async function cleanupLegacySchedules(): Promise<void> {
    if (!confirm('과거 날짜 및 계정 미연결 일정을 삭제합니다.')) return;
    try {
      const result = await coupangTravelApi.cleanupSchedules();
      toast.success(`${result.deleted}건 정리되었습니다.`);
      await fetchSchedulesAndStatus(false);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '정리 실패');
    }
  }

  onMount(async () => {
    await loadAll(true);
    refreshInterval = setInterval(() => {
      if (activeTab !== 'schedules') return;
      void fetchSchedulesAndStatus(false);
    }, 5000);
  });

  onDestroy(() => {
    cleanupPolling();
  });


</script>

<div class="space-y-6">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-bold">쿠팡 여행상품 모니터링</h1>
    <button
      class="btn btn-secondary btn-sm"
      onclick={() => loadAll(true)}
      disabled={loading}
    >
      새로고침
    </button>
  </div>

  {#if error}
    <div class="rounded bg-red-100 px-4 py-3 text-red-800" role="alert">
      {error}
      <button class="ml-2 text-sm underline" onclick={clearMessages}>닫기</button>
    </div>
  {/if}

  <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
    <div class="card text-center">
      <div class="text-3xl font-bold text-foreground">{statusSummary.total_schedules}</div>
      <div class="text-sm text-muted-foreground">전체 일정</div>
    </div>
    <div class="card text-center">
      <div class="text-3xl font-bold text-primary">{statusSummary.enabled_schedules}</div>
      <div class="text-sm text-muted-foreground">활성 일정</div>
    </div>
    <div class="card text-center">
      <div class="text-3xl font-bold text-success">{statusSummary.active_schedules}</div>
      <div class="text-sm text-muted-foreground">동작 중</div>
    </div>
  </div>

  <TabNav tabs={coupangTabs} bind:activeTab variant="primary" queryParam="tab" />

  {#if activeTab === 'schedules'}
    <section class="card">
      <h2 class="text-lg font-semibold mb-4">상품 등록</h2>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700" for="url">상품 URL</label>
          <input
            id="url"
            type="text"
            placeholder="https://trip.coupang.com/tp/products/..."
            bind:value={newUrl}
            class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700" for="vpid">vendor_item_package_id</label>
          <input
            id="vpid"
            type="text"
            placeholder="패키지 ID"
            bind:value={newVendorItemPackageId}
            class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700" for="name">이름</label>
          <input
            id="name"
            type="text"
            placeholder="상품 이름"
            bind:value={newName}
            class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          />
        </div>
      </div>
      <button
        class="mt-3 rounded bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50"
        onclick={submitTarget}
        disabled={submittingTarget}
      >
        {submittingTarget ? '등록 중...' : '상품 등록'}
      </button>
    </section>

    <section class="card">
      <h2 class="text-lg font-semibold mb-4">일정 추가</h2>
      {#if accounts.length === 0}
        <div class="mb-4 flex items-center justify-between rounded bg-amber-50 border border-amber-200 px-4 py-3">
          <span class="text-sm text-amber-800">쿠팡 계정이 등록되어 있지 않습니다. 계정 없이도 일정을 추가할 수 있지만, 로그인이 필요할 경우 모니터링이 동작하지 않을 수 있습니다.</span>
          <button
            class="ml-4 shrink-0 rounded bg-amber-500 px-3 py-1 text-sm font-medium text-white hover:bg-amber-600"
            onclick={() => { window.location.href = '/system?tab=browsers'; }}
          >계정 등록</button>
        </div>
      {/if}
      <div class="grid gap-3 sm:grid-cols-3">
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700" for="target-select">상품 선택</label>
          <select
            id="target-select"
            bind:value={selectedTargetId}
            class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          >
            <option value="">-- 상품 선택 --</option>
            {#each targets as target (target.id)}
              <option value={target.id}>{target.name} ({target.product_id})</option>
            {/each}
          </select>
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700" for="date-input">날짜</label>
          <input
            id="date-input"
            type="date"
            bind:value={newDate}
            class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700" for="account-select">쿠팡 계정</label>
          <select
            id="account-select"
            bind:value={selectedAccountId}
            class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          >
            <option value="">-- 계정 선택 --</option>
            {#each accounts as account (account.id)}
              <option value={account.id}>{account.profile_name ?? account.identifier ?? `계정 #${account.id}`}</option>
            {/each}
          </select>
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-gray-700" for="times-input">알림 시간대 (선택)</label>
          <input
            id="times-input"
            type="text"
            bind:value={newTimes}
            placeholder="10:00,11:00,14:00-19:00"
            class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          />
        </div>
      </div>
      <button
        class="mt-3 rounded bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50"
        onclick={submitSchedule}
        disabled={submittingSchedule}
      >
        {submittingSchedule ? '추가 중...' : '일정 추가'}
      </button>
    </section>

    <section class="card">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-lg font-semibold">등록된 상품 ({targets.length})</h2>
      </div>
      {#if targets.length === 0}
        <p class="text-sm text-muted-foreground">등록된 상품이 없습니다.</p>
      {:else}
        <div class="overflow-x-auto">
          <table class="table">
            <thead>
              <tr>
                <th>상품명</th>
                <th>product_id</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {#each targets as target (target.id)}
                <tr>
                  <td>{target.name}</td>
                  <td class="text-sm text-muted-foreground">{target.product_id}</td>
                  <td>
                    <button class="btn btn-danger btn-xs" onclick={() => deleteTarget(target.id)}>삭제</button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>

    <section class="card">
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
        <div>
          <label for="schedule-search" class="block text-sm font-medium text-foreground mb-1">검색</label>
          <input id="schedule-search" class="input" bind:value={scheduleFilters.search} placeholder="상품명 / product_id" />
        </div>
        <div>
          <label for="schedule-status" class="block text-sm font-medium text-foreground mb-1">활성 상태</label>
          <select id="schedule-status" class="input" bind:value={scheduleFilters.is_enabled}>
            <option value="all">전체</option>
            <option value="enabled">활성</option>
            <option value="disabled">비활성</option>
          </select>
        </div>
        <div>
          <label for="schedule-date-from" class="block text-sm font-medium text-foreground mb-1">시작일</label>
          <input id="schedule-date-from" type="date" class="input" bind:value={scheduleFilters.date_from} />
        </div>
        <div>
          <label for="schedule-date-to" class="block text-sm font-medium text-foreground mb-1">종료일</label>
          <input id="schedule-date-to" type="date" class="input" bind:value={scheduleFilters.date_to} />
        </div>
      </div>

      <div class="mb-4 flex items-center justify-between">
        <div class="text-sm text-muted-foreground">
          총 {filteredSchedules.length}건
          {#if selection.count > 0}
            <span class="ml-2 text-primary">({selection.count}건 선택)</span>
          {/if}
        </div>
        <div class="flex gap-2">
          {#if selection.count > 0}
            <button class="btn btn-secondary btn-sm" onclick={() => runBulkAction('enable')}>일괄 활성화</button>
            <button class="btn btn-secondary btn-sm" onclick={() => runBulkAction('disable')}>일괄 비활성화</button>
            <button class="btn btn-danger btn-sm" onclick={() => runBulkAction('delete')}>일괄 삭제</button>
          {/if}
          <button class="btn btn-secondary btn-sm" onclick={cleanupLegacySchedules}>과거 일정 정리</button>
        </div>
      </div>

      {#if loading}
        <div class="flex justify-center items-center h-40">
          <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600"></div>
        </div>
      {:else if filteredSchedules.length === 0}
        <p class="text-sm text-muted-foreground">조건에 맞는 일정이 없습니다.</p>
      {:else}
        <div class="overflow-x-auto">
          <table class="table">
            <thead>
              <tr>
                <th class="w-8">
                  <input
                    type="checkbox"
                    checked={selection.isAllSelected(filteredSchedules.map((schedule) => schedule.id))}
                    indeterminate={
                      selection.count > 0 &&
                      !selection.isAllSelected(filteredSchedules.map((schedule) => schedule.id))
                    }
                    onchange={() => selection.selectAll(filteredSchedules.map((schedule) => schedule.id))}
                  />
                </th>
                <th>상품</th>
                <th>날짜</th>
                <th>상태</th>
                <th>동작</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {#each filteredSchedules as schedule (schedule.id)}
                <tr class={selection.has(schedule.id) ? 'bg-primary-light' : ''}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selection.has(schedule.id)}
                      onchange={() => selection.toggle(schedule.id)}
                    />
                  </td>
                  <td>
                    <div class="font-medium text-sm">{schedule.item_name ?? schedule.business_name ?? '-'}</div>
                    <div class="text-xs text-muted-foreground">{schedule.product_id ?? '-'}</div>
                  </td>
                  <td class="text-sm">{schedule.date}</td>
                  <td>
                    <button
                      class={schedule.is_enabled ? 'btn btn-success btn-xs' : 'btn btn-secondary btn-xs'}
                      onclick={() => toggleSchedule(schedule)}
                    >
                      {schedule.is_enabled ? '활성' : '비활성'}
                    </button>
                  </td>
                  <td>
                    {#if schedule.is_enabled && schedule.is_active}
                      <span class="badge badge-success">동작중</span>
                    {:else}
                      <span class="badge badge-gray">대기</span>
                    {/if}
                  </td>
                  <td>
                    <div class="flex gap-2">
                      <button class="btn btn-danger btn-xs" onclick={() => deleteSchedule(schedule.id)}>삭제</button>
                    </div>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>
  {/if}

  {#if activeTab === 'history'}
    <CoupangMonitoringHistory />
  {/if}
</div>
