<script lang="ts">
  import { onMount } from 'svelte';
  import { scheduleApi, businessApi, accountApi, itemApi, scheduleRecurringApi } from '$lib/api';
  import type { ScheduleWithContext, Business, BusinessWithItems, BizItem, Account, MonitorScheduleUpdate, MonitorScheduleCreate, RecurringRuleWithContext, RecurringRuleCreate, TargetPattern } from '$lib/types';

  let schedules: ScheduleWithContext[] = [];
  let businesses: Business[] = [];
  let accounts: Account[] = [];
  let loading = true;
  let error: string | null = null;

  // 탭 상태
  let activeTab: 'schedules' | 'recurring' = 'schedules';

  // 반복 규칙 관련 상태
  let recurringRules: RecurringRuleWithContext[] = [];
  let recurringLoading = false;
  let recurringError: string | null = null;

  // 반복 규칙 생성 모달 상태
  let showRecurringCreateModal = false;
  let recurringCreateLoading = false;
  let recurringCreateError: string | null = null;
  let recurringSelectedBusinessItems: BizItem[] = [];

  // 반복 규칙 생성 폼
  let recurringForm = {
    name: '',
    business_id: null as number | null,
    biz_item_id: null as number | null,
    account_id: null as number | null,
    recurrence_day: 4, // 금요일
    trigger_time: '12:00',
    auto_booking_enabled: false,
    target_patterns: [] as Array<{
      day_offset: number;
      label: string;
      times: string;
      time_range: string;
      use_time_range: boolean;
    }>
  };

  // 요일 상수
  const WEEKDAY_NAMES = ['월', '화', '수', '목', '금', '토', '일'];

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
    custom_interval: false,
    account_id: null as number | null
  };

  // 간격 포맷팅
  function formatInterval(seconds: number | null | undefined): string {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds}초`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}분`;
    return `${Math.floor(seconds / 3600)}시간`;
  }

  // 시간 포맷팅 (HH:MM:SS)
  function formatTime(isoString: string | null | undefined): string {
    if (!isoString) return '-';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return '-';
    }
  }

  // 남은 시간 계산
  function getRemainingTime(nextRunTime: string | null | undefined): string {
    if (!nextRunTime) return '-';
    try {
      const next = new Date(nextRunTime);
      const now = new Date();
      const diffSeconds = Math.floor((next.getTime() - now.getTime()) / 1000);
      if (diffSeconds <= 0) return '곧 실행';
      const mins = Math.floor(diffSeconds / 60);
      const secs = diffSeconds % 60;
      if (mins > 0) return `${mins}분 ${secs}초`;
      return `${secs}초`;
    } catch {
      return '-';
    }
  }

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

  async function fetchRecurringRules() {
    recurringLoading = true;
    recurringError = null;
    try {
      recurringRules = await scheduleRecurringApi.list();
    } catch (e) {
      recurringError = e instanceof Error ? e.message : '반복 규칙 로드 실패';
    } finally {
      recurringLoading = false;
    }
  }

  async function handleToggleRecurringRule(rule: RecurringRuleWithContext) {
    try {
      if (rule.is_enabled) {
        await scheduleRecurringApi.disable(rule.id);
      } else {
        await scheduleRecurringApi.enable(rule.id);
      }
      await fetchRecurringRules();
    } catch (e) {
      alert('상태 변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleDeleteRecurringRule(rule: RecurringRuleWithContext) {
    if (!confirm(`${rule.business_name} - ${rule.item_name}\n"${rule.name}" 반복 규칙을 삭제하시겠습니까?`)) return;
    try {
      await scheduleRecurringApi.delete(rule.id);
      await fetchRecurringRules();
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleTriggerRecurringRule(rule: RecurringRuleWithContext) {
    if (!confirm(`"${rule.name}" 규칙을 수동으로 트리거하시겠습니까?\n일정이 즉시 생성됩니다.`)) return;
    try {
      const result = await scheduleRecurringApi.trigger(rule.id);
      alert(`${result.created_count}개의 일정이 생성되었습니다.`);
      await fetchRecurringRules();
      await fetchSchedules();
    } catch (e) {
      alert('트리거 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  function formatNextTrigger(nextTriggerAt: string | null): string {
    if (!nextTriggerAt) return '-';
    const date = new Date(nextTriggerAt);
    const now = new Date();
    const diffMs = date.getTime() - now.getTime();
    if (diffMs < 0) return '대기 중';

    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));

    if (diffDays > 0) return `${diffDays}일 ${diffHours}시간 후`;
    if (diffHours > 0) return `${diffHours}시간 후`;
    const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
    return `${diffMins}분 후`;
  }

  function formatTargetPatterns(patterns: Array<{day_offset: number; label?: string; times?: string[]; time_range?: string}> | null | undefined): string {
    if (!patterns || !Array.isArray(patterns)) return '-';
    return patterns.map(p => {
      if (!p || typeof p !== 'object') return '';
      const day = p.label || `D+${p.day_offset ?? 0}`;
      const time = p.times?.join(',') || p.time_range || '';
      return `${day}: ${time}`;
    }).filter(s => s).join(' / ') || '-';
  }

  // 반복 규칙 생성 관련 함수들
  async function handleRecurringBusinessSelect() {
    if (!recurringForm.business_id) {
      recurringSelectedBusinessItems = [];
      recurringForm.biz_item_id = null;
      return;
    }
    try {
      recurringSelectedBusinessItems = await businessApi.getItems(recurringForm.business_id);
      recurringForm.biz_item_id = null;
    } catch (e) {
      console.error('아이템 목록 로드 실패:', e);
      recurringSelectedBusinessItems = [];
    }
  }

  function openRecurringCreateModal() {
    recurringForm = {
      name: '',
      business_id: null,
      biz_item_id: null,
      account_id: null,
      recurrence_day: 4,
      trigger_time: '12:00',
      auto_booking_enabled: false,
      target_patterns: []
    };
    recurringSelectedBusinessItems = [];
    recurringCreateError = null;
    showRecurringCreateModal = true;
  }

  function addRecurringTargetPattern() {
    recurringForm.target_patterns = [
      ...recurringForm.target_patterns,
      {
        day_offset: recurringForm.target_patterns.length + 3,
        label: '',
        times: '',
        time_range: '',
        use_time_range: false
      }
    ];
  }

  function removeRecurringTargetPattern(index: number) {
    recurringForm.target_patterns = recurringForm.target_patterns.filter((_, i) => i !== index);
  }

  // 트리거 요일 기준 day_offset에 해당하는 요일 계산
  function getRecurringDayLabel(dayOffset: number): string {
    const targetDay = (recurringForm.recurrence_day + dayOffset) % 7;
    return WEEKDAY_NAMES[targetDay] + '요일';
  }

  async function createRecurringRule() {
    if (!recurringForm.biz_item_id) {
      recurringCreateError = '상품을 선택해주세요.';
      return;
    }
    if (!recurringForm.name.trim()) {
      recurringCreateError = '규칙 이름을 입력해주세요.';
      return;
    }
    if (recurringForm.target_patterns.length === 0) {
      recurringCreateError = '대상 패턴을 하나 이상 추가해주세요.';
      return;
    }

    recurringCreateLoading = true;
    recurringCreateError = null;

    try {
      // 타겟 패턴 변환
      const targetPatterns: TargetPattern[] = recurringForm.target_patterns.map(p => ({
        day_offset: p.day_offset,
        label: p.label || getRecurringDayLabel(p.day_offset),
        times: p.use_time_range ? undefined : p.times.split(',').map(t => t.trim()).filter(t => t),
        time_range: p.use_time_range ? p.time_range : undefined
      }));

      const data: RecurringRuleCreate = {
        type: 'monitor',
        biz_item_id: recurringForm.biz_item_id,
        account_id: recurringForm.account_id,
        name: recurringForm.name,
        recurrence_day: recurringForm.recurrence_day,
        trigger_time: recurringForm.trigger_time,
        target_patterns: targetPatterns,
        auto_booking_enabled: recurringForm.auto_booking_enabled
      };

      await scheduleRecurringApi.create(data);
      showRecurringCreateModal = false;
      await fetchRecurringRules();
    } catch (e) {
      recurringCreateError = e instanceof Error ? e.message : '생성 실패';
    } finally {
      recurringCreateLoading = false;
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

  async function handleToggleAutoBooking(schedule: ScheduleWithContext) {
    try {
      await scheduleApi.update(schedule.id, {
        auto_booking_enabled: !schedule.auto_booking_enabled
      });
      await fetchSchedules();
    } catch (e) {
      alert('자동예약 설정 변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
      interval: schedule.interval || 30,
      custom_interval: schedule.custom_interval || false,
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
        interval: editForm.custom_interval ? editForm.interval : undefined,
        custom_interval: editForm.custom_interval,
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

  // 네이버 예약 URL 생성
  function buildBookingUrl(schedule: ScheduleWithContext): string {
    return `https://booking.naver.com/booking/13/bizes/${schedule.business_id}/items/${schedule.item_biz_item_id}`;
  }

  // 클립보드 복사
  let copiedId: number | null = null;
  async function copyToClipboard(text: string, scheduleId: number) {
    try {
      await navigator.clipboard.writeText(text);
      copiedId = scheduleId;
      setTimeout(() => {
        copiedId = null;
      }, 2000);
    } catch (e) {
      console.error('클립보드 복사 실패:', e);
      alert('클립보드 복사에 실패했습니다.');
    }
  }

  onMount(() => {
    fetchSchedules();
    fetchBusinesses();
    fetchAccounts();
    fetchRecurringRules();
  });
</script>

<div class="p-6">
  <div class="mb-6 flex justify-between items-center">
    <h2 class="text-2xl font-bold text-gray-900">일정 관리</h2>
    <div class="flex gap-2">
      {#if activeTab === 'schedules'}
        <button class="btn btn-primary btn-sm" on:click={openCreateModal}>
          일정 등록
        </button>
        <button class="btn btn-secondary btn-sm" on:click={fetchSchedules}>
          새로고침
        </button>
      {:else}
        <button class="btn btn-secondary btn-sm" on:click={fetchRecurringRules}>
          새로고침
        </button>
        <button class="btn btn-primary btn-sm" on:click={openRecurringCreateModal}>
          + 반복 규칙 등록
        </button>
      {/if}
    </div>
  </div>

  <!-- 탭 네비게이션 -->
  <div class="border-b border-gray-200 mb-6">
    <nav class="flex space-x-8">
      <button
        class="py-2 px-1 border-b-2 font-medium text-sm {activeTab === 'schedules' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
        on:click={() => activeTab = 'schedules'}
      >
        일정 목록
        <span class="ml-2 px-2 py-0.5 text-xs rounded-full {activeTab === 'schedules' ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-600'}">{schedules.length}</span>
      </button>
      <button
        class="py-2 px-1 border-b-2 font-medium text-sm {activeTab === 'recurring' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
        on:click={() => activeTab = 'recurring'}
      >
        반복 규칙
        <span class="ml-2 px-2 py-0.5 text-xs rounded-full {activeTab === 'recurring' ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-600'}">{recurringRules.length}</span>
      </button>
    </nav>
  </div>

  {#if activeTab === 'schedules'}
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
              <th>링크</th>
              <th>시간</th>
              <th>간격</th>
              <th>계정</th>
              <th>상태</th>
              <th>마지막 체크</th>
              <th>다음 실행</th>
              <th>자동예약</th>
              <th class="w-32">작업</th>
            </tr>
          </thead>
          <tbody>
            {#each schedules as schedule (schedule.id)}
              {@const status = getStatusBadge(schedule.run_status, schedule.is_enabled)}
              {@const dateInfo = formatDate(schedule.date)}
              <tr class="{!schedule.is_enabled ? 'opacity-60' : ''} {schedule.error_count > 0 ? 'bg-red-50' : ''}">
                <td>
                  <div class="flex items-center gap-2">
                    <span class="font-medium">{dateInfo.date}</span>
                    {#if dateInfo.badge}
                      <span class="badge {dateInfo.badge === '지남' ? 'badge-gray' : dateInfo.badge === '오늘' ? 'badge-warning' : 'badge-info'}">{dateInfo.badge}</span>
                    {/if}
                  </div>
                </td>
                <td>
                  <div class="flex items-center gap-2">
                    <span>{schedule.business_name}</span>
                    {#if !schedule.business_is_enabled}
                      <span class="badge badge-gray text-xs">비활성</span>
                    {/if}
                  </div>
                </td>
                <td>
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
                <td>
                  <button
                    class="btn btn-xs {copiedId === schedule.id ? 'btn-success' : 'btn-secondary'}"
                    on:click={() => copyToClipboard(buildBookingUrl(schedule), schedule.id)}
                    title={buildBookingUrl(schedule)}
                  >
                    {copiedId === schedule.id ? '복사됨' : '복사'}
                  </button>
                </td>
                <td>
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
                <td>
                  {#if schedule.custom_interval}
                    <span class="text-blue-600 font-medium" title="수동 설정">{formatInterval(schedule.interval)}</span>
                  {:else}
                    <span class="text-gray-500" title="자동 (날짜 기반)">{formatInterval(schedule.interval)}</span>
                  {/if}
                </td>
                <td>
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
                <td class="text-xs text-gray-600 whitespace-nowrap">
                  {formatTime(schedule.last_check_time)}
                </td>
                <td class="text-xs whitespace-nowrap">
                  {#if schedule.run_status === 'running'}
                    <span class="text-green-600 font-medium">실행 중</span>
                  {:else if schedule.run_status === 'queued'}
                    <span class="text-blue-600">{getRemainingTime(schedule.next_run_time)}</span>
                  {:else}
                    <span class="text-gray-400">-</span>
                  {/if}
                </td>
                <td>
                  <div class="flex items-center gap-2">
                    <button
                      class="btn btn-xs {schedule.auto_booking_enabled ? 'btn-success' : 'btn-secondary'}"
                      on:click={() => handleToggleAutoBooking(schedule)}
                      title={schedule.auto_booking_enabled ? '자동예약 해제' : '자동예약 등록'}
                    >
                      {schedule.auto_booking_enabled ? 'ON' : 'OFF'}
                    </button>
                    {#if schedule.booking_count > 0}
                      <span class="text-green-600 font-medium">{schedule.booking_count}건</span>
                    {/if}
                  </div>
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
  {/if}

  <!-- 반복 규칙 탭 -->
  {#if activeTab === 'recurring'}
    {#if recurringLoading}
      <div class="flex justify-center items-center h-64">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    {:else if recurringError}
      <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
        {recurringError}
      </div>
    {:else if recurringRules.length === 0}
      <div class="card text-center py-12">
        <p class="text-gray-500 mb-4">등록된 반복 규칙이 없습니다.</p>
        <p class="text-sm text-gray-400">반복 규칙은 매주 특정 요일/시간에 일정을 자동으로 생성합니다.</p>
      </div>
    {:else}
      <div class="card">
        <div class="mb-4 text-sm text-gray-600">
          총 {recurringRules.length}개의 반복 규칙
        </div>
        <div class="overflow-x-auto">
          <table class="table">
            <thead>
              <tr>
                <th>이름</th>
                <th>업체</th>
                <th>아이템</th>
                <th>트리거</th>
                <th>대상 패턴</th>
                <th>상태</th>
                <th>다음 실행</th>
                <th>마지막 실행</th>
                <th class="w-32">작업</th>
              </tr>
            </thead>
            <tbody>
              {#each recurringRules as rule (rule.id)}
                <tr class="{!rule.is_enabled ? 'opacity-60' : ''}">
                  <td class="font-medium">{rule.name}</td>
                  <td>{rule.business_name}</td>
                  <td>{rule.item_name}</td>
                  <td>
                    <div class="text-sm">
                      <span class="font-medium">{WEEKDAY_NAMES[rule.recurrence_day]}요일</span>
                      <span class="text-gray-500 ml-1">{rule.trigger_time}</span>
                    </div>
                  </td>
                  <td>
                    <div class="text-xs text-gray-600 max-w-xs truncate" title={formatTargetPatterns(rule.target_patterns)}>
                      {formatTargetPatterns(rule.target_patterns)}
                    </div>
                  </td>
                  <td
                    class="cursor-pointer hover:bg-gray-100"
                    on:click={() => handleToggleRecurringRule(rule)}
                    title={rule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                  >
                    <span class="badge {rule.is_enabled ? 'badge-success' : 'badge-gray'}">
                      {rule.is_enabled ? '활성' : '비활성'}
                    </span>
                  </td>
                  <td class="text-xs">
                    {#if rule.is_enabled && rule.next_trigger_at}
                      <div class="text-blue-600 font-medium">{formatNextTrigger(rule.next_trigger_at)}</div>
                      <div class="text-gray-400">{new Date(rule.next_trigger_at).toLocaleString('ko-KR')}</div>
                    {:else}
                      <span class="text-gray-400">-</span>
                    {/if}
                  </td>
                  <td class="text-xs text-gray-600">
                    {#if rule.last_triggered_at}
                      {new Date(rule.last_triggered_at).toLocaleString('ko-KR')}
                    {:else}
                      <span class="text-gray-400">-</span>
                    {/if}
                  </td>
                  <td>
                    <div class="flex gap-1">
                      <button
                        class="btn btn-info btn-xs"
                        on:click={() => handleTriggerRecurringRule(rule)}
                        title="수동 트리거"
                      >
                        실행
                      </button>
                      <button
                        class="btn btn-danger btn-xs"
                        on:click={() => handleDeleteRecurringRule(rule)}
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
          <label class="block text-sm font-medium text-gray-700 mb-2">모니터링 간격</label>
          <div class="space-y-2">
            <label class="flex items-center gap-2">
              <input type="checkbox" bind:checked={editForm.custom_interval} />
              <span class="text-sm text-gray-700">수동 설정</span>
            </label>
            {#if editForm.custom_interval}
              <div class="flex items-center gap-2">
                <input
                  id="edit-interval"
                  type="number"
                  class="input w-24"
                  bind:value={editForm.interval}
                  min="5"
                  max="3600"
                />
                <span class="text-sm text-gray-600">초</span>
              </div>
            {:else}
              {@const dateInfo = formatDate(editSchedule?.date || '')}
              <div class="text-sm text-gray-500 bg-gray-50 px-3 py-2 rounded">
                기본값: <span class="font-medium text-gray-700">{formatInterval(editSchedule?.interval)}</span>
                <span class="text-gray-400 ml-1">({dateInfo.badge || '날짜 기준'})</span>
              </div>
              <p class="text-xs text-gray-400">
                D-1 이하: 30초 / D-3 이하: 1분 / D-7 이하: 5분 / D-7 초과: 15분
              </p>
            {/if}
          </div>
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

<!-- 반복 규칙 생성 모달 -->
{#if showRecurringCreateModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
      <div class="p-4 border-b sticky top-0 bg-white">
        <h3 class="text-lg font-semibold">반복 모니터링 규칙 생성</h3>
      </div>

      <form on:submit|preventDefault={createRecurringRule} class="p-4 space-y-4">
        {#if recurringCreateError}
          <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
            {recurringCreateError}
          </div>
        {/if}

        <!-- 규칙 이름 -->
        <div>
          <label for="recurring-name" class="block text-sm font-medium text-gray-700 mb-1">규칙 이름</label>
          <input
            id="recurring-name"
            type="text"
            class="input"
            bind:value={recurringForm.name}
            placeholder="예: 금요일 정기 오픈"
            required
          />
        </div>

        <!-- 대상 상품 -->
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label for="recurring-business" class="block text-sm font-medium text-gray-700 mb-1">업체</label>
            <select
              id="recurring-business"
              class="input"
              bind:value={recurringForm.business_id}
              on:change={handleRecurringBusinessSelect}
              required
            >
              <option value={null}>업체 선택</option>
              {#each businesses as business}
                <option value={business.id}>{business.name}</option>
              {/each}
            </select>
          </div>
          <div>
            <label for="recurring-item" class="block text-sm font-medium text-gray-700 mb-1">상품</label>
            <select
              id="recurring-item"
              class="input"
              bind:value={recurringForm.biz_item_id}
              disabled={!recurringForm.business_id}
              required
            >
              <option value={null}>상품 선택</option>
              {#each recurringSelectedBusinessItems as item}
                <option value={item.id}>{item.name}</option>
              {/each}
            </select>
          </div>
        </div>

        <!-- 계정 선택 -->
        <div>
          <label for="recurring-account" class="block text-sm font-medium text-gray-700 mb-1">사용 계정 (선택사항)</label>
          <select id="recurring-account" class="input" bind:value={recurringForm.account_id}>
            <option value={null}>계정 선택 안함</option>
            {#each accounts as account}
              <option value={account.id}>{account.name}</option>
            {/each}
          </select>
        </div>

        <!-- 반복 설정 -->
        <div class="border-t pt-4">
          <h4 class="text-sm font-medium text-gray-900 mb-3">반복 설정</h4>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label for="recurring-day" class="block text-sm font-medium text-gray-700 mb-1">트리거 요일</label>
              <select id="recurring-day" class="input" bind:value={recurringForm.recurrence_day}>
                {#each WEEKDAY_NAMES as name, idx}
                  <option value={idx}>{name}요일</option>
                {/each}
              </select>
            </div>
            <div>
              <label for="recurring-time" class="block text-sm font-medium text-gray-700 mb-1">트리거 시간 (오픈 시간)</label>
              <input
                id="recurring-time"
                type="time"
                class="input"
                bind:value={recurringForm.trigger_time}
                required
              />
            </div>
          </div>
        </div>

        <!-- 대상 날짜/시간 패턴 -->
        <div class="border-t pt-4">
          <div class="flex justify-between items-center mb-3">
            <h4 class="text-sm font-medium text-gray-900">대상 날짜/시간 패턴</h4>
            <button type="button" class="btn btn-secondary btn-sm" on:click={addRecurringTargetPattern}>
              + 패턴 추가
            </button>
          </div>

          {#if recurringForm.target_patterns.length === 0}
            <div class="text-sm text-gray-500 text-center py-4 bg-gray-50 rounded">
              패턴을 추가해주세요. 트리거 날짜 기준 D+N일에 대한 시간을 설정합니다.
            </div>
          {:else}
            <div class="space-y-3">
              {#each recurringForm.target_patterns as pattern, idx}
                <div class="border rounded-lg p-3 bg-gray-50">
                  <div class="flex items-center gap-3 mb-2">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium">D+</span>
                      <input
                        type="number"
                        class="input w-16"
                        bind:value={pattern.day_offset}
                        min="0"
                        max="30"
                      />
                    </div>
                    <span class="text-sm text-gray-500">({getRecurringDayLabel(pattern.day_offset)})</span>
                    <input
                      type="text"
                      class="input flex-1"
                      bind:value={pattern.label}
                      placeholder="라벨 (선택)"
                    />
                    <button
                      type="button"
                      class="btn btn-danger btn-sm"
                      on:click={() => removeRecurringTargetPattern(idx)}
                    >
                      삭제
                    </button>
                  </div>
                  <div class="flex items-center gap-3">
                    <label class="flex items-center gap-2">
                      <input type="radio" bind:group={pattern.use_time_range} value={false} />
                      <span class="text-sm">시간 목록</span>
                    </label>
                    <label class="flex items-center gap-2">
                      <input type="radio" bind:group={pattern.use_time_range} value={true} />
                      <span class="text-sm">시간 범위</span>
                    </label>
                  </div>
                  <div class="mt-2">
                    {#if pattern.use_time_range}
                      <input
                        type="text"
                        class="input"
                        bind:value={pattern.time_range}
                        placeholder="예: 13:00-19:00"
                      />
                    {:else}
                      <input
                        type="text"
                        class="input"
                        bind:value={pattern.times}
                        placeholder="예: 18:00, 19:00"
                      />
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>

        <!-- 모니터링 옵션 -->
        <div class="border-t pt-4">
          <h4 class="text-sm font-medium text-gray-900 mb-3">모니터링 옵션</h4>
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={recurringForm.auto_booking_enabled} />
            <span class="text-sm">자동 예약 활성화</span>
          </label>
          <p class="text-xs text-gray-500 mt-1">생성되는 일정에서 슬롯 발견 시 자동으로 예약을 수행합니다.</p>
        </div>

        <!-- 버튼 -->
        <div class="flex justify-end gap-3 pt-4 border-t">
          <button
            type="button"
            class="btn btn-secondary"
            on:click={() => showRecurringCreateModal = false}
          >
            취소
          </button>
          <button
            type="submit"
            class="btn btn-primary"
            disabled={recurringCreateLoading}
          >
            {recurringCreateLoading ? '생성 중...' : '생성'}
          </button>
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
  .btn-success {
    background-color: #dcfce7;
    color: #166534;
    border: 1px solid #86efac;
  }
  .btn-success:hover {
    background-color: #bbf7d0;
  }
  .btn-info {
    background-color: #dbeafe;
    color: #1e40af;
    border: 1px solid #93c5fd;
  }
  .btn-info:hover {
    background-color: #bfdbfe;
  }
</style>
