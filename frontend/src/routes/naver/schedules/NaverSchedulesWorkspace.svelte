<script lang="ts">
	import { Badge, Button } from '$lib/components/ui';
	import TabNav from '$lib/components/layout/TabNav.svelte';

	import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { scheduleApi, businessApi, serviceAccountApi, itemApi, scheduleRecurringApi } from '$lib/api';
  import type { ScheduleWithContext, Business, BusinessWithItems, BizItem, ServiceAccountWithProfile, MonitorScheduleUpdate, MonitorScheduleCreate, RecurringRuleWithContext, RecurringRuleCreate, TargetPattern } from '$lib/types';
  import AutoBookingList from '$lib/components/schedules/AutoBookingList.svelte';
  import MonitoringHistory from '$lib/components/MonitoringHistory.svelte';
  import BusinessManager from '$lib/components/businesses/BusinessManager.svelte';
  import PopupUrlMonitorPanel from '$lib/components/naver/PopupUrlMonitorPanel.svelte';
  import { buildMonitoringHref } from '$lib/utils/monitoringRouteState';
  import { createSelection } from '$lib/utils/selection.svelte';
  import { toast } from '$lib/stores/toast';
  import { confirm } from '$lib/stores/confirm';

  type ScheduleTab = 'schedules' | 'booking' | 'recurring' | 'history' | 'businesses' | 'popup_monitor';

  interface Props {
    sub?: string | null;
    unified?: boolean;
  }

  let { sub = null, unified = false }: Props = $props();

  let schedules: ScheduleWithContext[] = [];
  let businesses: Business[] = [];
  let accounts: ServiceAccountWithProfile[] = [];
  let loading = true;
  let error: string | null = null;

  // 멀티 선택
  const selection = createSelection();

  function errorMessage(e: unknown): string {
    return e instanceof Error ? e.message : '알 수 없는 오류';
  }

  async function bulkToggleEnabled(enable: boolean) {
    if (selection.count === 0) return;
    const confirmed = await confirm({
      title: enable ? '일정 일괄 활성화' : '일정 일괄 비활성화',
      message: `선택한 ${selection.count}개 일정을 ${enable ? '활성화' : '비활성화'}하시겠습니까?`,
      confirmText: enable ? '활성화' : '비활성화'
    });
    if (!confirmed) return;
    try {
      for (const id of selection.toArray()) {
        if (enable) {
          await scheduleApi.enable(id);
        } else {
          await scheduleApi.disable(id);
        }
      }
      selection.clear();
      await fetchSchedules();
    } catch (e) {
      toast.error('일괄 처리 실패: ' + errorMessage(e));
    }
  }

  async function bulkDelete() {
    if (selection.count === 0) return;
    const confirmed = await confirm({
      title: '일정 일괄 삭제',
      message: `선택한 ${selection.count}개 일정을 삭제하시겠습니까?`,
      confirmText: '삭제',
      variant: 'danger'
    });
    if (!confirmed) return;
    try {
      for (const id of selection.toArray()) {
        await scheduleApi.delete(id);
      }
      selection.clear();
      await fetchSchedules();
    } catch (e) {
      toast.error('일괄 삭제 실패: ' + errorMessage(e));
    }
  }

  // 탭 상태
  let activeTab: ScheduleTab = 'schedules';

  function normalizeScheduleTab(tab: string | null | undefined): ScheduleTab {
    if (tab === 'booking' || tab === 'recurring' || tab === 'history' || tab === 'businesses' || tab === 'popup_monitor') {
      return tab;
    }
    return 'schedules';
  }

  // URL 파라미터에서 탭 초기화
  $: {
    const tab = unified ? sub : $page.url.searchParams.get('tab');
    activeTab = normalizeScheduleTab(tab);
  }

  function handleScheduleTabChange(tabId: string) {
    const next = normalizeScheduleTab(tabId);
    activeTab = next;
    if (!unified) return;
    goto(buildMonitoringHref({ type: 'naver', view: 'schedules', sub: next }, $page.url), {
      replaceState: true,
      keepFocus: true,
      noScroll: true
    });
  }

  // 탭 목록 (카운트 포함)
  $: scheduleTabs = [
    { id: 'schedules', label: '전체 일정', count: schedules.length || undefined },
    { id: 'booking', label: '자동 예약' },
    { id: 'recurring', label: '반복 규칙', count: recurringRules.length || undefined },
    { id: 'popup_monitor', label: '팝업 URL 모니터' },
    { id: 'history', label: '실행 내역' },
    { id: 'businesses', label: '업체 관리' },
  ];

  // 반복 규칙 관련 상태
  let recurringRules: RecurringRuleWithContext[] = [];
  let recurringLoading = false;
  let recurringError: string | null = null;

  // 반복 규칙 생성 모달 상태
  let showRecurringCreateModal = false;
  let recurringCreateLoading = false;
  let recurringCreateError: string | null = null;
  let recurringUrlParsing = false;
  let recurringUrlParsed = false;
  let recurringParsedInfo: { business_name?: string; item_name?: string } = {};

  // 반복 규칙 생성 폼
  let recurringForm = {
    url: '',
    name: '',
    biz_item_id: null as number | null,
    service_account_id: null as number | null,
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
    time_range: '',
    use_time_range: false,
    is_enabled: true,
    interval: 10,
    custom_interval: false,
    service_account_id: null as number | null,
    monitoring_mode: 'anonymous' as 'legacy' | 'anonymous'
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
    service_account_id: null as number | null,
    monitoring_mode: 'anonymous' as 'legacy' | 'anonymous'
  };
  let selectedBusinessItems: BizItem[] = [];
  let createLoading = false;

  // 복제 모달
  let showDuplicateModal = false;
  let duplicateSchedule: ScheduleWithContext | null = null;
  let duplicateForm = {
    date: '',
    times: '',
    service_account_id: null as number | null
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
      toast.error('상태 변경 실패: ' + errorMessage(e));
    }
  }

  async function handleDeleteRecurringRule(rule: RecurringRuleWithContext) {
    const confirmed = await confirm({
      title: '반복 규칙 삭제',
      message: `${rule.business_name} - ${rule.item_name}\n"${rule.name}" 반복 규칙을 삭제하시겠습니까?`,
      confirmText: '삭제',
      variant: 'danger'
    });
    if (!confirmed) return;
    try {
      await scheduleRecurringApi.delete(rule.id);
      await fetchRecurringRules();
    } catch (e) {
      toast.error('삭제 실패: ' + errorMessage(e));
    }
  }

  async function handleTriggerRecurringRule(rule: RecurringRuleWithContext) {
    const confirmed = await confirm({
      title: '반복 규칙 수동 실행',
      message: `"${rule.name}" 규칙을 수동으로 트리거하시겠습니까?\n일정이 즉시 생성됩니다.`,
      confirmText: '실행'
    });
    if (!confirmed) return;
    try {
      const result = await scheduleRecurringApi.trigger(rule.id);
      toast.success(`${result.created_count}개의 일정이 생성되었습니다.`);
      await fetchRecurringRules();
      await fetchSchedules();
    } catch (e) {
      toast.error('트리거 실패: ' + errorMessage(e));
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
  async function parseRecurringUrl() {
    if (!recurringForm.url) return;

    recurringUrlParsing = true;
    recurringCreateError = null;

    try {
      // DB에서 biz_item 정보 조회 (import API 사용)
      const importResult = await businessApi.importFromUrl({ url: recurringForm.url });

      if (importResult.biz_item) {
        recurringForm.biz_item_id = importResult.biz_item.id;
        recurringParsedInfo = {
          business_name: importResult.business?.name,
          item_name: importResult.biz_item?.name
        };
        recurringUrlParsed = true;

        // 이름 자동 설정
        if (!recurringForm.name && recurringParsedInfo.item_name) {
          recurringForm.name = `${recurringParsedInfo.item_name} 반복 모니터링`;
        }
      } else {
        recurringCreateError = 'URL에서 상품 정보를 찾을 수 없습니다. 먼저 업체 관리에서 URL을 등록해주세요.';
      }
    } catch (e) {
      recurringCreateError = e instanceof Error ? e.message : 'URL 파싱 실패';
      recurringUrlParsed = false;
    } finally {
      recurringUrlParsing = false;
    }
  }

  // 패턴 복사 모달 상태
  let showPatternCopyModal = false;
  let patternCopySource: RecurringRuleWithContext | null = null;

  // 반복 규칙 수정 모달 상태
  let showRecurringEditModal = false;
  let editRecurringRule: RecurringRuleWithContext | null = null;
  let recurringEditLoading = false;
  let recurringEditError: string | null = null;

  // 반복 규칙 수정 폼
  let recurringEditForm = {
    name: '',
    service_account_id: null as number | null,
    recurrence_day: 0,
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

  function openRecurringCreateModal() {
    recurringForm = {
      url: '',
      name: '',
      biz_item_id: null,
      service_account_id: null,
      recurrence_day: 4,
      trigger_time: '12:00',
      auto_booking_enabled: false,
      target_patterns: []
    };
    recurringUrlParsed = false;
    recurringParsedInfo = {};
    recurringCreateError = null;
    showRecurringCreateModal = true;
  }

  function openPatternCopyModal() {
    patternCopySource = null;
    showPatternCopyModal = true;
  }

  // 반복 규칙 수정 모달 열기
  function openRecurringEditModal(rule: RecurringRuleWithContext) {
    editRecurringRule = rule;
    recurringEditForm = {
      name: rule.name,
      service_account_id: rule.service_account_id,
      recurrence_day: rule.recurrence_day,
      trigger_time: rule.trigger_time,
      auto_booking_enabled: rule.auto_booking_enabled ?? false,
      target_patterns: (rule.target_patterns || []).map(p => ({
        day_offset: p.day_offset ?? 0,
        label: p.label || '',
        times: p.times?.join(', ') || '',
        time_range: p.time_range || '',
        use_time_range: !!p.time_range && !p.times?.length
      }))
    };
    recurringEditError = null;
    showRecurringEditModal = true;
  }

  // 반복 규칙 수정 시 day_offset에 따른 요일 라벨 계산
  function getRecurringEditDayLabel(dayOffset: number): string {
    const targetDay = (recurringEditForm.recurrence_day + dayOffset) % 7;
    return WEEKDAY_NAMES[targetDay] + '요일';
  }

  // 반복 규칙 수정 폼에 패턴 추가
  function addRecurringEditTargetPattern() {
    recurringEditForm.target_patterns = [
      ...recurringEditForm.target_patterns,
      {
        day_offset: recurringEditForm.target_patterns.length + 3,
        label: '',
        times: '',
        time_range: '',
        use_time_range: false
      }
    ];
  }

  // 반복 규칙 수정 폼에서 패턴 삭제
  function removeRecurringEditTargetPattern(index: number) {
    recurringEditForm.target_patterns = recurringEditForm.target_patterns.filter((_, i) => i !== index);
  }

  // 반복 규칙 수정 저장
  async function handleUpdateRecurringRule() {
    if (!editRecurringRule) return;

    if (!recurringEditForm.name.trim()) {
      recurringEditError = '규칙 이름을 입력해주세요.';
      return;
    }
    if (recurringEditForm.target_patterns.length === 0) {
      recurringEditError = '대상 패턴을 하나 이상 추가해주세요.';
      return;
    }

    recurringEditLoading = true;
    recurringEditError = null;

    try {
      // 타겟 패턴 변환
      const targetPatterns: TargetPattern[] = recurringEditForm.target_patterns.map(p => ({
        day_offset: p.day_offset,
        label: p.label || getRecurringEditDayLabel(p.day_offset),
        times: p.use_time_range ? undefined : p.times.split(',').map(t => t.trim()).filter(t => t),
        time_range: p.use_time_range ? p.time_range : undefined
      }));

      await scheduleRecurringApi.update(editRecurringRule.id, {
        name: recurringEditForm.name,
        service_account_id: recurringEditForm.service_account_id,
        recurrence_day: recurringEditForm.recurrence_day,
        trigger_time: recurringEditForm.trigger_time,
        target_patterns: targetPatterns,
        auto_booking_enabled: recurringEditForm.auto_booking_enabled
      });

      showRecurringEditModal = false;
      editRecurringRule = null;
      await fetchRecurringRules();
    } catch (e) {
      recurringEditError = e instanceof Error ? e.message : '수정 실패';
    } finally {
      recurringEditLoading = false;
    }
  }

  function copyPatternFromRule(rule: RecurringRuleWithContext) {
    if (!rule.target_patterns || !Array.isArray(rule.target_patterns)) return;

    // 기존 패턴을 복사된 패턴으로 대체
    recurringForm.target_patterns = rule.target_patterns.map(p => ({
      day_offset: p.day_offset ?? 0,
      label: p.label || '',
      times: p.times?.join(', ') || '',
      time_range: p.time_range || '',
      use_time_range: !!p.time_range && !p.times?.length
    }));

    showPatternCopyModal = false;
    patternCopySource = null;
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
        service_account_id: recurringForm.service_account_id,
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
      accounts = await serviceAccountApi.listActive('naver');
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
      toast.error('상태 변경 실패: ' + errorMessage(e));
    }
  }

  async function handleToggleAutoBooking(schedule: ScheduleWithContext) {
    try {
      await scheduleApi.update(schedule.id, {
        auto_booking_enabled: !schedule.auto_booking_enabled
      });
      await fetchSchedules();
    } catch (e) {
      toast.error('자동예약 설정 변경 실패: ' + errorMessage(e));
    }
  }

  async function handleDeleteSchedule(schedule: ScheduleWithContext) {
    const confirmed = await confirm({
      title: '일정 삭제',
      message: `${schedule.business_name} - ${schedule.item_name}\n${schedule.date} 일정을 삭제하시겠습니까?`,
      confirmText: '삭제',
      variant: 'danger'
    });
    if (!confirmed) return;
    try {
      await scheduleApi.delete(schedule.id);
      await fetchSchedules();
    } catch (e) {
      toast.error('삭제 실패: ' + errorMessage(e));
    }
  }

  function openEditModal(schedule: ScheduleWithContext) {
    editSchedule = schedule;
    editForm = {
      times: schedule.times?.join(', ') || '',
      time_range: schedule.time_range || '',
      use_time_range: !!schedule.time_range && !schedule.times?.length,
      is_enabled: schedule.is_enabled,
      interval: schedule.interval || 30,
      custom_interval: schedule.custom_interval || false,
      service_account_id: schedule.service_account_id,
      monitoring_mode: schedule.monitoring_mode || 'anonymous'
    };
    showEditModal = true;
  }

  async function handleUpdateSchedule() {
    if (!editSchedule) return;
    try {
      const times = editForm.use_time_range ? undefined : (editForm.times ? editForm.times.split(',').map(t => t.trim()).filter(t => t) : []);
      const time_range = editForm.use_time_range ? editForm.time_range : undefined;
      const updateData: MonitorScheduleUpdate = {
        times,
        time_range,
        is_enabled: editForm.is_enabled,
        interval: editForm.custom_interval ? editForm.interval : undefined,
        custom_interval: editForm.custom_interval,
        service_account_id: editForm.service_account_id,
        monitoring_mode: editForm.monitoring_mode
      };
      await scheduleApi.update(editSchedule.id, updateData);
      showEditModal = false;
      editSchedule = null;
      await fetchSchedules();
    } catch (e) {
      toast.error('수정 실패: ' + errorMessage(e));
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
      service_account_id: null,
      monitoring_mode: 'anonymous'
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
    if (!createForm.url) {
      toast.warning('URL을 입력해주세요.');
      return;
    }
    createLoading = true;
    try {
      const result = await businessApi.importFromUrl({
        url: createForm.url,
        item_name: createForm.item_name || undefined,
        business_name: createForm.business_name || undefined,
        auto_booking_enabled: false
      });
      if (result.success) {
        const bizName = result.business?.name || result.business_details?.['name'] as string | undefined;
        const itemName = result.biz_item?.name || result.item_details?.['name'] as string | undefined;
        const nameInfo = bizName || itemName ? ` (${[bizName, itemName].filter(Boolean).join(' / ')})` : '';
        showCreateModal = false;
        await fetchSchedules();
        toast.success(`일정이 등록되었습니다.${nameInfo}`);
      } else {
        toast.error(result.message || '등록 실패');
      }
    } catch (e) {
      toast.error('등록 실패: ' + errorMessage(e));
    } finally {
      createLoading = false;
    }
  }

  // 아이템 선택으로 일정 생성
  async function handleCreateFromSelect() {
    if (!createForm.item_id || !createForm.date) {
      toast.warning('아이템과 날짜를 선택해주세요.');
      return;
    }
    createLoading = true;
    try {
      const times = createForm.times ? createForm.times.split(',').map(t => t.trim()).filter(t => t) : [];
      const scheduleData: MonitorScheduleCreate = {
        date: createForm.date,
        times,
        is_enabled: createForm.is_enabled,
        service_account_id: createForm.service_account_id,
        monitoring_mode: createForm.monitoring_mode,
      };
      await itemApi.createSchedule(createForm.item_id, scheduleData);
      showCreateModal = false;
      await fetchSchedules();
      toast.success('일정이 등록되었습니다.');
    } catch (e) {
      toast.error('등록 실패: ' + errorMessage(e));
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
      service_account_id: schedule.service_account_id
    };
    showDuplicateModal = true;
  }

  // 일정 복제
  async function handleDuplicate() {
    if (!duplicateSchedule || !duplicateForm.date) {
      toast.warning('날짜를 입력해주세요.');
      return;
    }
    try {
      const times = duplicateForm.times ? duplicateForm.times.split(',').map(t => t.trim()).filter(t => t) : [];
      const scheduleData: MonitorScheduleCreate = {
        date: duplicateForm.date,
        times,
        is_enabled: true,
        service_account_id: duplicateForm.service_account_id,
        monitoring_mode: 'anonymous',
      };
      await itemApi.createSchedule(duplicateSchedule.biz_item_pk, scheduleData);
      showDuplicateModal = false;
      duplicateSchedule = null;
      await fetchSchedules();
    } catch (e) {
      toast.error('복제 실패: ' + errorMessage(e));
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
      toast.error('클립보드 복사에 실패했습니다.');
    }
  }

  onMount(() => {
    fetchSchedules();
    fetchBusinesses();
    fetchAccounts();
    fetchRecurringRules();
  });
</script>

<div>
  <div class="mb-6 flex justify-end">
    <div class="flex gap-2">
      <a href="/monitoring?type=naver&view=schedules&sub=businesses" class="btn btn-secondary btn-sm">
        업체/상품 관리
      </a>
      {#if activeTab === 'schedules'}
        <Button variant="primary" size="sm" onclick={openCreateModal}>
          일정 등록
        </Button>
        <Button variant="secondary" size="sm" onclick={fetchSchedules}>
          새로고침
        </Button>
      {:else if activeTab === 'recurring'}
        <Button variant="secondary" size="sm" onclick={fetchRecurringRules}>
          새로고침
        </Button>
        <Button variant="primary" size="sm" onclick={openRecurringCreateModal}>
          + 반복 규칙 등록
        </Button>
      {/if}
    </div>
  </div>

  <!-- 탭 네비게이션 -->
  {#if unified}
    <TabNav tabs={scheduleTabs} bind:activeTab variant="secondary" overflow="wrap" onTabChange={handleScheduleTabChange} />
  {:else}
    <TabNav tabs={scheduleTabs} bind:activeTab variant="secondary" queryParam="tab" overflow="wrap" />
  {/if}

  {#if activeTab === 'schedules'}
  <!-- 필터 영역 -->
  <div class="card mb-6">
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
      <div>
        <label for="search" class="block text-sm font-medium text-foreground mb-1">검색</label>
        <input
          id="search"
          type="text"
          class="input"
          placeholder="업체명/아이템명"
          bind:value={filters.search}
          onkeydown={(e) => e.key === 'Enter' && handleSearch()}
        />
      </div>
      <div>
        <label for="business" class="block text-sm font-medium text-foreground mb-1">업체</label>
        <select id="business" class="input" bind:value={filters.business_id}>
          <option value={null}>전체</option>
          {#each businesses as business}
            <option value={business.id}>{business.name}</option>
          {/each}
        </select>
      </div>
      <div>
        <label for="status" class="block text-sm font-medium text-foreground mb-1">상태</label>
        <select id="status" class="input" bind:value={filters.is_enabled}>
          <option value={null}>전체</option>
          <option value={true}>활성</option>
          <option value={false}>비활성</option>
        </select>
      </div>
      <div>
        <label for="date_from" class="block text-sm font-medium text-foreground mb-1">시작일</label>
        <input id="date_from" type="date" class="input" bind:value={filters.date_from} />
      </div>
      <div>
        <label for="date_to" class="block text-sm font-medium text-foreground mb-1">종료일</label>
        <input id="date_to" type="date" class="input" bind:value={filters.date_to} />
      </div>
    </div>
    <div class="flex gap-2">
      <Button variant="primary" onclick={handleSearch}>검색</Button>
      <Button variant="secondary" onclick={clearFilters}>초기화</Button>
    </div>
  </div>

  <!-- 일정 목록 -->
  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else if schedules.length === 0}
    <div class="card text-center py-12">
      <p class="text-muted-foreground">등록된 일정이 없습니다.</p>
    </div>
  {:else}
    <div class="card">
      <div class="mb-4 flex items-center justify-between">
        <div class="text-sm text-muted-foreground">
          총 {schedules.length}개의 일정
          {#if selection.count > 0}
            <span class="ml-2 text-primary">({selection.count}개 선택)</span>
          {/if}
        </div>
        {#if selection.count > 0}
          <div class="flex gap-2">
            <Button variant="secondary" size="sm" onclick={() => bulkToggleEnabled(true)}>
              일괄 활성화
            </Button>
            <Button variant="secondary" size="sm" onclick={() => bulkToggleEnabled(false)}>
              일괄 비활성화
            </Button>
            <button class="btn btn-danger btn-sm" onclick={bulkDelete}>
              일괄 삭제
            </button>
          </div>
        {/if}
      </div>
      <div class="md:hidden space-y-3">
        {#each schedules as schedule (schedule.id)}
          {@const status = getStatusBadge(schedule.run_status, schedule.is_enabled)}
          {@const dateInfo = formatDate(schedule.date)}
          <article class="rounded-lg border border-border bg-white p-3 {!schedule.is_enabled ? 'opacity-60' : ''} {schedule.error_count > 0 ? 'border-red-200 bg-error-light' : ''} {selection.has(schedule.id) ? 'border-blue-200 bg-primary-light' : ''}">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <input
                    type="checkbox"
                    class="w-4 h-4 cursor-pointer"
                    checked={selection.has(schedule.id)}
                    onchange={() => selection.toggle(schedule.id)}
                    aria-label="일정 선택"
                  />
                  <button
                    class="text-left"
                    onclick={() => handleToggleSchedule(schedule)}
                    title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                  >
                    <span class="badge {status.class}">{status.text}</span>
                  </button>
                  {#if schedule.error_count > 0}
                    <span class="badge badge-error text-xs" title={schedule.last_error || ''}>
                      오류 {schedule.error_count}
                    </span>
                  {/if}
                </div>
                <div class="mt-2 min-w-0">
                  <p class="font-medium text-foreground break-words">
                    {schedule.business_name}
                    {#if !schedule.business_is_enabled}
                      <Badge variant="secondary" class="text-xs">OFF</Badge>
                    {/if}
                  </p>
                  <p class="text-xs text-muted-foreground break-words">
                    {schedule.item_name}
                    {#if !schedule.item_is_enabled}
                      <Badge variant="secondary" class="text-xs">OFF</Badge>
                    {/if}
                  </p>
                </div>
              </div>
              <button
                onclick={() => copyToClipboard(buildBookingUrl(schedule), schedule.id)}
                class="btn btn-secondary btn-xs shrink-0"
                title="예약 링크 복사"
              >
                {copiedId === schedule.id ? '복사됨' : '링크'}
              </button>
            </div>

            <div class="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div>
                <p class="text-xs text-muted-foreground">일정</p>
                <p class="font-medium text-foreground">
                  {dateInfo.date}
                  {#if dateInfo.badge}
                    <Badge
                      variant={dateInfo.badge === '지남' ? 'secondary' : dateInfo.badge === '오늘' ? 'warning' : 'info'}
                      class="text-xs"
                    >
                      {dateInfo.badge}
                    </Badge>
                  {/if}
                </p>
                <p class="text-xs text-muted-foreground">
                  {#if schedule.times && schedule.times.length > 0}
                    {schedule.times.join(', ')}
                  {:else if schedule.time_range}
                    {schedule.time_range}
                  {:else}
                    전체 시간
                  {/if}
                </p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">체크</p>
                <p class="text-foreground">최근: {formatTime(schedule.last_check_time)}</p>
                <p>
                  {#if schedule.run_status === 'running'}
                    <span class="text-success font-medium">실행 중</span>
                  {:else if schedule.run_status === 'queued'}
                    <span class="text-primary">다음: {getRemainingTime(schedule.next_run_time)}</span>
                  {:else}
                    <span class="text-muted-foreground">-</span>
                  {/if}
                </p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">간격</p>
                <p class="{schedule.custom_interval ? 'text-primary' : 'text-foreground'}">{formatInterval(schedule.interval)}</p>
              </div>
              <div>
                <p class="text-xs text-muted-foreground">계정</p>
                {#if schedule.account_name}
                  <Badge variant="info" class="text-xs">{schedule.account_name}</Badge>
                {:else}
                  <span class="text-muted-foreground text-sm">기본</span>
                {/if}
              </div>
            </div>

            <div class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
              <div class="flex items-center gap-2">
                <button
                  class="btn btn-xs {schedule.auto_booking_enabled ? 'btn-success' : 'btn-secondary'}"
                  onclick={() => handleToggleAutoBooking(schedule)}
                  title={schedule.auto_booking_enabled ? '자동예약 해제' : '자동예약 등록'}
                >
                  자동예약 {schedule.auto_booking_enabled ? 'ON' : 'OFF'}
                </button>
                {#if schedule.booking_count > 0}
                  <span class="text-success font-medium text-xs">예약 {schedule.booking_count}</span>
                {/if}
              </div>
              <div class="flex gap-1">
                <button class="btn btn-secondary btn-xs" onclick={() => openEditModal(schedule)}>수정</button>
                <button class="btn btn-secondary btn-xs" onclick={() => openDuplicateModal(schedule)}>복제</button>
                <button class="btn btn-danger btn-xs" onclick={() => handleDeleteSchedule(schedule)}>삭제</button>
              </div>
            </div>
          </article>
        {/each}
      </div>

      <div class="hidden md:block overflow-x-auto">
        <table class="table">
          <thead>
            <tr>
              <th class="w-8">
                <input
                  type="checkbox"
                  class="w-4 h-4 cursor-pointer"
                  checked={selection.isAllSelected(schedules.map(s => s.id))}
                  indeterminate={selection.count > 0 && !selection.isAllSelected(schedules.map(s => s.id))}
                  onchange={() => selection.selectAll(schedules.map(s => s.id))}
                  title="전체 선택/해제"
                />
              </th>
              <th>상태</th>
              <th>업체/아이템</th>
              <th>일정</th>
              <th class="hidden md:table-cell">계정</th>
              <th class="hidden lg:table-cell">체크</th>
              <th>예약</th>
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            {#each schedules as schedule (schedule.id)}
              {@const status = getStatusBadge(schedule.run_status, schedule.is_enabled)}
              {@const dateInfo = formatDate(schedule.date)}
              <tr class="{!schedule.is_enabled ? 'opacity-60' : ''} {schedule.error_count > 0 ? 'bg-error-light' : ''} {selection.has(schedule.id) ? 'bg-primary-light' : ''}">
                <!-- 체크박스 -->
                <td>
                  <input
                    type="checkbox"
                    class="w-4 h-4 cursor-pointer"
                    checked={selection.has(schedule.id)}
                    onchange={() => selection.toggle(schedule.id)}
                  />
                </td>
                <!-- 상태 (간격 포함) -->
                <td
                  class="cursor-pointer hover:bg-muted"
                  onclick={() => handleToggleSchedule(schedule)}
                  title={schedule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                >
                  <div class="flex items-center gap-1">
                    <span class="badge {status.class}">{status.text}</span>
                    {#if schedule.error_count > 0}
                      <span class="badge badge-error text-xs" title={schedule.last_error || ''}>
                        {schedule.error_count}
                      </span>
                    {/if}
                  </div>
                  <div class="text-xs text-muted-foreground mt-0.5">
                    {#if schedule.custom_interval}
                      <span class="text-primary" title="수동 설정">{formatInterval(schedule.interval)}</span>
                    {:else}
                      {formatInterval(schedule.interval)}
                    {/if}
                  </div>
                </td>
                <!-- 업체/아이템 + 링크 -->
                <td class="max-w-48">
                  <div class="flex items-center gap-1">
                    <div class="min-w-0 flex-1">
                      <div class="font-medium text-sm truncate flex items-center gap-1" title={schedule.business_name}>
                        {schedule.business_name}
                        {#if !schedule.business_is_enabled}
                          <Badge variant="secondary" class="text-xs">OFF</Badge>
                        {/if}
                      </div>
                      <div class="text-xs text-muted-foreground truncate flex items-center gap-1" title={schedule.item_name}>
                        {schedule.item_name}
                        {#if !schedule.item_is_enabled}
                          <Badge variant="secondary" class="text-xs">OFF</Badge>
                        {/if}
                      </div>
                    </div>
                    <button
                      onclick={(e) => { e.stopPropagation(); copyToClipboard(buildBookingUrl(schedule), schedule.id) }}
                      class="btn btn-secondary btn-xs p-1 shrink-0"
                      title="예약 링크 복사"
                    >
                      {#if copiedId === schedule.id}
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5 text-success">
                          <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                        </svg>
                      {:else}
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3.5 h-3.5">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
                        </svg>
                      {/if}
                    </button>
                  </div>
                </td>
                <!-- 일정 (날짜+시간 병합) -->
                <td>
                  <div class="text-sm">
                    <div class="flex items-center gap-1">
                      <span class="font-medium">{dateInfo.date}</span>
                      {#if dateInfo.badge}
                        <Badge
                          variant={dateInfo.badge === '지남' ? 'secondary' : dateInfo.badge === '오늘' ? 'warning' : 'info'}
                          class="text-xs"
                        >
                          {dateInfo.badge}
                        </Badge>
                      {/if}
                    </div>
                    <div class="text-xs text-muted-foreground">
                      {#if schedule.times && schedule.times.length > 0}
                        {#if schedule.times.length <= 2}
                          {schedule.times.join(', ')}
                        {:else}
                          {schedule.times.slice(0, 2).join(', ')}
                          <span class="text-muted-foreground">+{schedule.times.length - 2}</span>
                        {/if}
                      {:else if schedule.time_range}
                        {schedule.time_range}
                      {:else}
                        전체 시간
                      {/if}
                    </div>
                  </div>
                </td>
                <!-- 계정 (md 이상에서만 표시) -->
                <td class="hidden md:table-cell">
                  {#if schedule.account_name}
                    <Badge variant="info" class="text-xs">{schedule.account_name}</Badge>
                  {:else}
                    <span class="text-muted-foreground text-xs">기본</span>
                  {/if}
                </td>
                <!-- 체크 (마지막 체크 + 다음 실행 병합, lg 이상에서만 표시) -->
                <td class="hidden lg:table-cell text-xs whitespace-nowrap">
                  <div class="text-muted-foreground">
                    최근: {formatTime(schedule.last_check_time)}
                  </div>
                  <div>
                    {#if schedule.run_status === 'running'}
                      <span class="text-success font-medium">실행 중</span>
                    {:else if schedule.run_status === 'queued'}
                      <span class="text-primary">다음: {getRemainingTime(schedule.next_run_time)}</span>
                    {:else}
                      <span class="text-muted-foreground">-</span>
                    {/if}
                  </div>
                </td>
                <!-- 예약 (자동예약 토글 + 예약건수) -->
                <td>
                  <div class="flex items-center gap-1">
                    <button
                      class="btn btn-xs p-1 {schedule.auto_booking_enabled ? 'btn-success' : 'btn-secondary'}"
                      onclick={() => handleToggleAutoBooking(schedule)}
                      title={schedule.auto_booking_enabled ? '자동예약 해제' : '자동예약 등록'}
                    >
                      {#if schedule.auto_booking_enabled}
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                          <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z" clip-rule="evenodd" />
                        </svg>
                      {:else}
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
                        </svg>
                      {/if}
                    </button>
                    {#if schedule.booking_count > 0}
                      <span class="text-success font-medium text-xs">{schedule.booking_count}</span>
                    {/if}
                  </div>
                </td>
                <!-- 관리 (아이콘 버튼) -->
                <td>
                  <div class="flex gap-1">
                    <button
                      class="btn btn-secondary btn-xs p-1"
                      onclick={() => openEditModal(schedule)}
                      title="수정"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10" />
                      </svg>
                    </button>
                    <button
                      class="btn btn-secondary btn-xs p-1"
                      onclick={() => openDuplicateModal(schedule)}
                      title="복제"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" />
                      </svg>
                    </button>
                    <button
                      class="btn btn-danger btn-xs p-1"
                      onclick={() => handleDeleteSchedule(schedule)}
                      title="삭제"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                      </svg>
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

  <!-- 자동 예약 탭 -->
  {#if activeTab === 'booking'}
    <AutoBookingList />
  {/if}

  <!-- 반복 규칙 탭 -->
  {#if activeTab === 'recurring'}
    {#if recurringLoading}
      <div class="flex justify-center items-center h-64">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    {:else if recurringError}
      <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
        {recurringError}
      </div>
    {:else if recurringRules.length === 0}
      <div class="card text-center py-12">
        <p class="text-muted-foreground mb-4">등록된 반복 규칙이 없습니다.</p>
        <p class="text-sm text-muted-foreground">반복 규칙은 매주 특정 요일/시간에 일정을 자동으로 생성합니다.</p>
      </div>
    {:else}
      <div class="card">
        <div class="mb-4 text-sm text-muted-foreground">
          총 {recurringRules.length}개의 반복 규칙
        </div>
        <div class="md:hidden space-y-3">
          {#each recurringRules as rule (rule.id)}
            <article class="rounded-lg border border-border bg-white p-3 {!rule.is_enabled ? 'opacity-60 bg-background' : ''}">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <button
                    class="text-left"
                    onclick={() => handleToggleRecurringRule(rule)}
                    title={rule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                  >
                    <Badge variant={rule.is_enabled ? 'success' : 'secondary'}>
                      {rule.is_enabled ? '활성' : '비활성'}
                    </Badge>
                  </button>
                  {#if rule.auto_booking_enabled}
                    <span class="ml-1 text-xs text-success">자동예약</span>
                  {/if}
                  <p class="mt-2 font-medium text-foreground break-words">{rule.name}</p>
                  <p class="text-xs text-muted-foreground break-words">
                    {rule.business_name} / {rule.item_name}
                  </p>
                </div>
                <div class="flex gap-1 shrink-0">
                  <button class="btn btn-secondary btn-xs" onclick={() => openRecurringEditModal(rule)}>수정</button>
                  <button class="btn btn-info btn-xs" onclick={() => handleTriggerRecurringRule(rule)}>실행</button>
                  <button class="btn btn-danger btn-xs" onclick={() => handleDeleteRecurringRule(rule)}>삭제</button>
                </div>
              </div>

              <div class="mt-3 grid grid-cols-2 gap-2 text-sm">
                <div>
                  <p class="text-xs text-muted-foreground">트리거</p>
                  <p class="font-medium text-foreground">{WEEKDAY_NAMES[rule.recurrence_day]}요일 {rule.trigger_time}</p>
                </div>
                <div>
                  <p class="text-xs text-muted-foreground">다음 실행</p>
                  {#if rule.is_enabled && rule.next_trigger_at}
                    <p class="font-medium text-primary">{formatNextTrigger(rule.next_trigger_at)}</p>
                  {:else}
                    <p class="text-muted-foreground">-</p>
                  {/if}
                </div>
                <div>
                  <p class="text-xs text-muted-foreground">최근 실행</p>
                  {#if rule.last_triggered_at}
                    <p class="text-foreground">{new Date(rule.last_triggered_at).toLocaleDateString('ko-KR')}</p>
                  {:else}
                    <p class="text-muted-foreground">-</p>
                  {/if}
                </div>
                <div>
                  <p class="text-xs text-muted-foreground">대상 패턴</p>
                  <p class="text-foreground break-words">{formatTargetPatterns(rule.target_patterns)}</p>
                </div>
              </div>
            </article>
          {/each}
        </div>

        <div class="hidden md:block overflow-x-auto">
          <table class="table">
            <thead>
              <tr>
                <th>상태</th>
                <th>규칙/업체</th>
                <th>트리거</th>
                <th class="hidden md:table-cell">대상 패턴</th>
                <th class="hidden lg:table-cell">실행 정보</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {#each recurringRules as rule (rule.id)}
                <tr class="{!rule.is_enabled ? 'opacity-60' : ''}">
                  <!-- 상태 -->
                  <td
                    class="cursor-pointer hover:bg-muted"
                    onclick={() => handleToggleRecurringRule(rule)}
                    title={rule.is_enabled ? '클릭하여 비활성화' : '클릭하여 활성화'}
                  >
                    <Badge variant={rule.is_enabled ? 'success' : 'secondary'}>
                      {rule.is_enabled ? '활성' : '비활성'}
                    </Badge>
                    {#if rule.auto_booking_enabled}
                      <div class="text-xs text-success mt-0.5">자동예약</div>
                    {/if}
                  </td>
                  <!-- 규칙/업체 (이름+업체+아이템 병합) -->
                  <td class="max-w-48">
                    <div class="font-medium text-sm truncate" title={rule.name}>{rule.name}</div>
                    <div class="text-xs text-muted-foreground truncate" title="{rule.business_name} - {rule.item_name}">
                      {rule.business_name} / {rule.item_name}
                    </div>
                  </td>
                  <!-- 트리거 -->
                  <td>
                    <div class="text-sm">
                      <div class="font-medium">{WEEKDAY_NAMES[rule.recurrence_day]}요일</div>
                      <div class="text-xs text-muted-foreground">{rule.trigger_time}</div>
                    </div>
                  </td>
                  <!-- 대상 패턴 (md 이상에서만 표시) -->
                  <td class="hidden md:table-cell">
                    <div class="text-xs text-muted-foreground max-w-xs truncate" title={formatTargetPatterns(rule.target_patterns)}>
                      {formatTargetPatterns(rule.target_patterns)}
                    </div>
                  </td>
                  <!-- 실행 정보 (다음실행+마지막실행 병합, lg 이상에서만 표시) -->
                  <td class="hidden lg:table-cell text-xs whitespace-nowrap">
                    <div>
                      {#if rule.is_enabled && rule.next_trigger_at}
                        <span class="text-primary font-medium">다음: {formatNextTrigger(rule.next_trigger_at)}</span>
                      {:else}
                        <span class="text-muted-foreground">다음: -</span>
                      {/if}
                    </div>
                    <div class="text-muted-foreground">
                      {#if rule.last_triggered_at}
                        최근: {new Date(rule.last_triggered_at).toLocaleDateString('ko-KR')}
                      {:else}
                        최근: -
                      {/if}
                    </div>
                  </td>
                  <!-- 관리 (아이콘 버튼) -->
                  <td>
                    <div class="flex gap-1">
                      <button
                        class="btn btn-secondary btn-xs p-1"
                        onclick={() => openRecurringEditModal(rule)}
                        title="수정"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                          <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10" />
                        </svg>
                      </button>
                      <button
                        class="btn btn-info btn-xs p-1"
                        onclick={() => handleTriggerRecurringRule(rule)}
                        title="수동 트리거"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
                        </svg>
                      </button>
                      <button
                        class="btn btn-danger btn-xs p-1"
                        onclick={() => handleDeleteRecurringRule(rule)}
                        title="삭제"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                          <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                        </svg>
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

  <!-- 실행 내역 탭 -->
  {#if activeTab === 'popup_monitor'}
    <PopupUrlMonitorPanel />
  {/if}

  <!-- 실행 내역 탭 -->
  {#if activeTab === 'history'}
    <MonitoringHistory />
  {/if}

  <!-- 업체 관리 탭 -->
  {#if activeTab === 'businesses'}
    <BusinessManager />
  {/if}
</div>

<!-- 수정 모달 -->
{#if showEditModal && editSchedule}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">일정 수정</h3>
        <p class="text-sm text-muted-foreground mt-1">
          {editSchedule.business_name} - {editSchedule.item_name} ({editSchedule.date})
        </p>
      </div>
      <form onsubmit={(e) => { e.preventDefault(); handleUpdateSchedule(); }} class="p-4 space-y-4">
        <div>
          <p class="block text-sm font-medium text-foreground mb-2">시간 설정 방식</p>
          <div class="flex gap-4 mb-2">
            <label class="flex items-center gap-1">
              <input type="radio" bind:group={editForm.use_time_range} value={false} />
              <span class="text-sm">특정 시간</span>
            </label>
            <label class="flex items-center gap-1">
              <input type="radio" bind:group={editForm.use_time_range} value={true} />
              <span class="text-sm">시간 범위</span>
            </label>
          </div>
          {#if editForm.use_time_range}
            <input
              type="text"
              class="input"
              bind:value={editForm.time_range}
              placeholder="예: 13:00-20:00"
            />
            <p class="text-xs text-muted-foreground mt-1">시작-종료 시간 범위</p>
          {:else}
            <input
              id="edit-times"
              type="text"
              class="input"
              bind:value={editForm.times}
              placeholder="예: 10:00, 14:00, 18:00"
            />
            <p class="text-xs text-muted-foreground mt-1">쉼표로 구분하여 여러 시간 입력</p>
          {/if}
        </div>
        <div>
          <p class="block text-sm font-medium text-foreground mb-2">모니터링 간격</p>
          <div class="space-y-2">
            <label class="flex items-center gap-2">
              <input type="checkbox" bind:checked={editForm.custom_interval} />
              <span class="text-sm text-foreground">수동 설정</span>
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
                <span class="text-sm text-muted-foreground">초</span>
              </div>
            {:else}
              {@const dateInfo = formatDate(editSchedule?.date || '')}
              <div class="text-sm text-muted-foreground bg-background px-3 py-2 rounded">
                기본값: <span class="font-medium text-foreground">{formatInterval(editSchedule?.interval)}</span>
                <span class="text-muted-foreground ml-1">({dateInfo.badge || '날짜 기준'})</span>
              </div>
              <p class="text-xs text-muted-foreground">
                D-1 이하: 30초 / D-3 이하: 1분 / D-7 이하: 5분 / D-7 초과: 15분
              </p>
            {/if}
          </div>
        </div>
        <div>
          <label for="edit-account" class="block text-sm font-medium text-foreground mb-1">사용 계정</label>
          <select id="edit-account" class="input" bind:value={editForm.service_account_id}>
            <option value={null}>기본 계정</option>
            {#each accounts as account}
              <option value={account.id}>{account.profile_name}</option>
            {/each}
          </select>
        </div>
        <div>
          <label for="edit-monitoring-mode" class="block text-sm font-medium text-foreground mb-1">모니터링 모드</label>
          <select id="edit-monitoring-mode" class="input" bind:value={editForm.monitoring_mode}>
            <option value="anonymous">익명 모드 (기본값)</option>
            <option value="legacy">기존 방식 (로그인 탭 사용)</option>
          </select>
          <p class="text-xs text-muted-foreground mt-1">
            {#if editForm.monitoring_mode === 'anonymous'}
              재고 확인은 익명으로, 예약 시에만 탭을 사용합니다. 더 많은 스케줄을 동시에 모니터링할 수 있습니다.
            {:else}
              모든 작업에 로그인된 탭을 사용합니다. 안정성이 높지만 동시 모니터링 수가 제한됩니다.
            {/if}
          </p>
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={editForm.is_enabled} />
          <span class="text-sm font-medium text-foreground">활성화</span>
        </label>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" onclick={() => { showEditModal = false; editSchedule = null; }}>
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
            class="px-3 py-1 text-sm rounded-md {createMode === 'select' ? 'bg-primary text-white' : 'bg-secondary text-foreground'}"
            onclick={() => createMode = 'select'}
          >
            업체/아이템 선택
          </button>
          <button
            class="px-3 py-1 text-sm rounded-md {createMode === 'url' ? 'bg-primary text-white' : 'bg-secondary text-foreground'}"
            onclick={() => createMode = 'url'}
          >
            URL로 등록
          </button>
        </div>
      </div>

      {#if createMode === 'select'}
        <form onsubmit={(e) => { e.preventDefault(); handleCreateFromSelect(); }} class="p-4 space-y-4">
          <div>
            <label for="create-business" class="block text-sm font-medium text-foreground mb-1">업체</label>
            <select
              id="create-business"
              class="input"
              bind:value={createForm.business_id}
              onchange={handleBusinessSelect}
            >
              <option value={null}>업체 선택</option>
              {#each businesses as business}
                <option value={business.id}>{business.name}</option>
              {/each}
            </select>
          </div>
          <div>
            <label for="create-item" class="block text-sm font-medium text-foreground mb-1">아이템</label>
            <select id="create-item" class="input" bind:value={createForm.item_id} disabled={!createForm.business_id}>
              <option value={null}>아이템 선택</option>
              {#each selectedBusinessItems as item}
                <option value={item.id}>{item.name}</option>
              {/each}
            </select>
          </div>
          <div>
            <label for="create-date" class="block text-sm font-medium text-foreground mb-1">날짜</label>
            <input id="create-date" type="date" class="input" bind:value={createForm.date} />
          </div>
          <div>
            <label for="create-times" class="block text-sm font-medium text-foreground mb-1">시간 (쉼표 구분, 선택)</label>
            <input
              id="create-times"
              type="text"
              class="input"
              bind:value={createForm.times}
              placeholder="예: 10:00, 14:00, 18:00"
            />
            <p class="text-xs text-muted-foreground mt-1">비워두면 아이템의 시간 범위 설정을 따릅니다</p>
          </div>
          <div>
            <label for="create-account" class="block text-sm font-medium text-foreground mb-1">사용 계정</label>
            <select id="create-account" class="input" bind:value={createForm.service_account_id}>
              <option value={null}>기본 계정</option>
              {#each accounts as account}
                <option value={account.id}>{account.profile_name}</option>
              {/each}
            </select>
          </div>
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={createForm.is_enabled} />
            <span class="text-sm font-medium text-foreground">활성화</span>
          </label>
          <div class="flex justify-end gap-2 pt-4">
            <button type="button" class="btn btn-secondary" onclick={() => showCreateModal = false}>
              취소
            </button>
            <button type="submit" class="btn btn-primary" disabled={createLoading}>
              {createLoading ? '등록 중...' : '등록'}
            </button>
          </div>
        </form>
      {:else}
        <form onsubmit={(e) => { e.preventDefault(); handleCreateFromUrl(); }} class="p-4 space-y-4">
          <div>
            <label for="create-url" class="block text-sm font-medium text-foreground mb-1">네이버 예약 URL</label>
            <input
              id="create-url"
              type="url"
              class="input"
              bind:value={createForm.url}
              placeholder="https://booking.naver.com/booking/..."
            />
          </div>
          <div>
            <label for="create-item-name" class="block text-sm font-medium text-foreground mb-1">아이템 이름 <span class="text-muted-foreground font-normal">(자동 채움 가능)</span></label>
            <input
              id="create-item-name"
              type="text"
              class="input"
              bind:value={createForm.item_name}
              placeholder="비워두면 URL에서 자동으로 가져옵니다"
            />
          </div>
          <div>
            <label for="create-business-name" class="block text-sm font-medium text-foreground mb-1">업체 이름 (선택)</label>
            <input
              id="create-business-name"
              type="text"
              class="input"
              bind:value={createForm.business_name}
              placeholder="자동으로 가져옵니다"
            />
            <p class="text-xs text-muted-foreground mt-1">비워두면 URL에서 자동으로 가져옵니다</p>
          </div>
          <div class="flex justify-end gap-2 pt-4">
            <button type="button" class="btn btn-secondary" onclick={() => showCreateModal = false}>
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
        <p class="text-sm text-muted-foreground mt-1">
          {duplicateSchedule.business_name} - {duplicateSchedule.item_name}
        </p>
      </div>
      <form onsubmit={(e) => { e.preventDefault(); handleDuplicate(); }} class="p-4 space-y-4">
        <div>
          <label for="dup-date" class="block text-sm font-medium text-foreground mb-1">날짜</label>
          <input id="dup-date" type="date" class="input" bind:value={duplicateForm.date} />
        </div>
        <div>
          <label for="dup-times" class="block text-sm font-medium text-foreground mb-1">시간 (쉼표 구분)</label>
          <input
            id="dup-times"
            type="text"
            class="input"
            bind:value={duplicateForm.times}
            placeholder="예: 10:00, 14:00, 18:00"
          />
          <p class="text-xs text-muted-foreground mt-1">비워두면 아이템의 시간 범위 설정을 따릅니다</p>
        </div>
        <div>
          <label for="dup-account" class="block text-sm font-medium text-foreground mb-1">사용 계정</label>
          <select id="dup-account" class="input" bind:value={duplicateForm.service_account_id}>
            <option value={null}>기본 계정</option>
            {#each accounts as account}
              <option value={account.id}>{account.profile_name}</option>
            {/each}
          </select>
        </div>
        <div class="flex justify-end gap-2 pt-4">
          <button type="button" class="btn btn-secondary" onclick={() => { showDuplicateModal = false; duplicateSchedule = null; }}>
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

      <form onsubmit={(e) => { e.preventDefault(); createRecurringRule(); }} class="p-4 space-y-4">
        {#if recurringCreateError}
          <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg text-sm">
            {recurringCreateError}
          </div>
        {/if}

        <!-- 규칙 이름 -->
        <div>
          <label for="recurring-name" class="block text-sm font-medium text-foreground mb-1">규칙 이름</label>
          <input
            id="recurring-name"
            type="text"
            class="input"
            bind:value={recurringForm.name}
            placeholder="예: 금요일 정기 오픈"
            required
          />
        </div>

        <!-- URL 입력 -->
        <div>
          <label for="recurring-url" class="block text-sm font-medium text-foreground mb-1">네이버 예약 URL</label>
          <div class="flex gap-2">
            <input
              id="recurring-url"
              type="url"
              class="input flex-1"
              bind:value={recurringForm.url}
              placeholder="https://booking.naver.com/booking/..."
              disabled={recurringUrlParsed}
              required
            />
            {#if !recurringUrlParsed}
              <button
                type="button"
                class="btn btn-secondary"
                onclick={parseRecurringUrl}
                disabled={recurringUrlParsing || !recurringForm.url}
              >
                {#if recurringUrlParsing}
                  확인 중...
                {:else}
                  확인
                {/if}
              </button>
            {:else}
              <button
                type="button"
                class="btn btn-secondary"
                onclick={() => { recurringUrlParsed = false; recurringParsedInfo = {}; recurringForm.biz_item_id = null; }}
              >
                변경
              </button>
            {/if}
          </div>
          {#if recurringUrlParsed && recurringParsedInfo.business_name}
            <div class="mt-2 p-2 bg-success-light border border-green-200 rounded text-sm text-success">
              {recurringParsedInfo.business_name} - {recurringParsedInfo.item_name}
            </div>
          {/if}
        </div>

        <!-- 계정 선택 -->
        <div>
          <label for="recurring-account" class="block text-sm font-medium text-foreground mb-1">사용 계정 (선택사항)</label>
          <select id="recurring-account" class="input" bind:value={recurringForm.service_account_id}>
            <option value={null}>계정 선택 안함</option>
            {#each accounts as account}
              <option value={account.id}>{account.profile_name}</option>
            {/each}
          </select>
        </div>

        <!-- 반복 설정 -->
        <div class="border-t pt-4">
          <h4 class="text-sm font-medium text-foreground mb-3">반복 설정</h4>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label for="recurring-day" class="block text-sm font-medium text-foreground mb-1">트리거 요일</label>
              <select id="recurring-day" class="input" bind:value={recurringForm.recurrence_day}>
                {#each WEEKDAY_NAMES as name, idx}
                  <option value={idx}>{name}요일</option>
                {/each}
              </select>
            </div>
            <div>
              <label for="recurring-time" class="block text-sm font-medium text-foreground mb-1">트리거 시간 (오픈 시간)</label>
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
            <h4 class="text-sm font-medium text-foreground">대상 날짜/시간 패턴</h4>
            <div class="flex gap-2">
              {#if recurringRules.length > 0}
                <button type="button" class="btn btn-info btn-sm" onclick={openPatternCopyModal}>
                  기존 패턴 복사
                </button>
              {/if}
              <button type="button" class="btn btn-secondary btn-sm" onclick={addRecurringTargetPattern}>
                + 패턴 추가
              </button>
            </div>
          </div>

          {#if recurringForm.target_patterns.length === 0}
            <div class="text-sm text-muted-foreground text-center py-4 bg-background rounded">
              패턴을 추가해주세요. 트리거 날짜 기준 D+N일에 대한 시간을 설정합니다.
            </div>
          {:else}
            <div class="space-y-3">
              {#each recurringForm.target_patterns as pattern, idx}
                <div class="border rounded-lg p-3 bg-background">
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
                    <span class="text-sm text-muted-foreground">({getRecurringDayLabel(pattern.day_offset)})</span>
                    <input
                      type="text"
                      class="input flex-1"
                      bind:value={pattern.label}
                      placeholder="라벨 (선택)"
                    />
                    <button
                      type="button"
                      class="btn btn-danger btn-sm"
                      onclick={() => removeRecurringTargetPattern(idx)}
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
          <h4 class="text-sm font-medium text-foreground mb-3">모니터링 옵션</h4>
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={recurringForm.auto_booking_enabled} />
            <span class="text-sm">자동 예약 활성화</span>
          </label>
          <p class="text-xs text-muted-foreground mt-1">생성되는 일정에서 슬롯 발견 시 자동으로 예약을 수행합니다.</p>
        </div>

        <!-- 버튼 -->
        <div class="flex justify-end gap-3 pt-4 border-t">
          <button
            type="button"
            class="btn btn-secondary"
            onclick={() => showRecurringCreateModal = false}
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

<!-- 패턴 복사 모달 -->
{#if showPatternCopyModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[60]">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[70vh] overflow-y-auto">
      <div class="p-4 border-b sticky top-0 bg-white">
        <h3 class="text-lg font-semibold">대상 패턴 복사</h3>
        <p class="text-sm text-muted-foreground mt-1">기존 반복 규칙에서 대상 패턴을 복사합니다.</p>
      </div>

      <div class="p-4">
        {#if recurringRules.length === 0}
          <div class="text-center py-8 text-muted-foreground">
            복사할 수 있는 반복 규칙이 없습니다.
          </div>
        {:else}
          <div class="space-y-2">
            {#each recurringRules as rule (rule.id)}
              <button
                type="button"
                class="w-full text-left p-3 border rounded-lg hover:bg-primary-light hover:border-blue-300 transition-colors"
                onclick={() => copyPatternFromRule(rule)}
              >
                <div class="flex items-center justify-between">
                  <div>
                    <div class="font-medium text-foreground">{rule.name}</div>
                    <div class="text-sm text-muted-foreground">{rule.business_name} - {rule.item_name}</div>
                    <div class="text-xs text-muted-foreground mt-1">
                      {formatTargetPatterns(rule.target_patterns)}
                    </div>
                  </div>
                  <span class="text-primary text-sm">선택</span>
                </div>
              </button>
            {/each}
          </div>
        {/if}
      </div>

      <div class="p-4 border-t flex justify-end">
        <button
          type="button"
          class="btn btn-secondary"
          onclick={() => showPatternCopyModal = false}
        >
          취소
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- 반복 규칙 수정 모달 -->
{#if showRecurringEditModal && editRecurringRule}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
      <div class="p-4 border-b sticky top-0 bg-white">
        <h3 class="text-lg font-semibold">반복 모니터링 규칙 수정</h3>
        <p class="text-sm text-muted-foreground mt-1">
          {editRecurringRule.business_name} - {editRecurringRule.item_name}
        </p>
      </div>

      <form onsubmit={(e) => { e.preventDefault(); handleUpdateRecurringRule(); }} class="p-4 space-y-4">
        {#if recurringEditError}
          <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg text-sm">
            {recurringEditError}
          </div>
        {/if}

        <!-- 규칙 이름 -->
        <div>
          <label for="recurring-edit-name" class="block text-sm font-medium text-foreground mb-1">규칙 이름</label>
          <input
            id="recurring-edit-name"
            type="text"
            class="input"
            bind:value={recurringEditForm.name}
            placeholder="예: 금요일 정기 오픈"
            required
          />
        </div>

        <!-- 계정 선택 -->
        <div>
          <label for="recurring-edit-account" class="block text-sm font-medium text-foreground mb-1">사용 계정 (선택사항)</label>
          <select id="recurring-edit-account" class="input" bind:value={recurringEditForm.service_account_id}>
            <option value={null}>계정 선택 안함</option>
            {#each accounts as account}
              <option value={account.id}>{account.profile_name}</option>
            {/each}
          </select>
        </div>

        <!-- 반복 설정 -->
        <div class="border-t pt-4">
          <h4 class="text-sm font-medium text-foreground mb-3">반복 설정</h4>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label for="recurring-edit-day" class="block text-sm font-medium text-foreground mb-1">트리거 요일</label>
              <select id="recurring-edit-day" class="input" bind:value={recurringEditForm.recurrence_day}>
                {#each WEEKDAY_NAMES as name, idx}
                  <option value={idx}>{name}요일</option>
                {/each}
              </select>
            </div>
            <div>
              <label for="recurring-edit-time" class="block text-sm font-medium text-foreground mb-1">트리거 시간 (오픈 시간)</label>
              <input
                id="recurring-edit-time"
                type="time"
                class="input"
                bind:value={recurringEditForm.trigger_time}
                required
              />
            </div>
          </div>
        </div>

        <!-- 대상 날짜/시간 패턴 -->
        <div class="border-t pt-4">
          <div class="flex justify-between items-center mb-3">
            <h4 class="text-sm font-medium text-foreground">대상 날짜/시간 패턴</h4>
            <button type="button" class="btn btn-secondary btn-sm" onclick={addRecurringEditTargetPattern}>
              + 패턴 추가
            </button>
          </div>

          {#if recurringEditForm.target_patterns.length === 0}
            <div class="text-sm text-muted-foreground text-center py-4 bg-background rounded">
              패턴을 추가해주세요. 트리거 날짜 기준 D+N일에 대한 시간을 설정합니다.
            </div>
          {:else}
            <div class="space-y-3">
              {#each recurringEditForm.target_patterns as pattern, idx}
                <div class="border rounded-lg p-3 bg-background">
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
                    <span class="text-sm text-muted-foreground">({getRecurringEditDayLabel(pattern.day_offset)})</span>
                    <input
                      type="text"
                      class="input flex-1"
                      bind:value={pattern.label}
                      placeholder="라벨 (선택)"
                    />
                    <button
                      type="button"
                      class="btn btn-danger btn-sm"
                      onclick={() => removeRecurringEditTargetPattern(idx)}
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
          <h4 class="text-sm font-medium text-foreground mb-3">모니터링 옵션</h4>
          <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={recurringEditForm.auto_booking_enabled} />
            <span class="text-sm">자동 예약 활성화</span>
          </label>
          <p class="text-xs text-muted-foreground mt-1">생성되는 일정에서 슬롯 발견 시 자동으로 예약을 수행합니다.</p>
        </div>

        <!-- 버튼 -->
        <div class="flex justify-end gap-3 pt-4 border-t">
          <button
            type="button"
            class="btn btn-secondary"
            onclick={() => { showRecurringEditModal = false; editRecurringRule = null; }}
          >
            취소
          </button>
          <button
            type="submit"
            class="btn btn-primary"
            disabled={recurringEditLoading}
          >
            {recurringEditLoading ? '저장 중...' : '저장'}
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
