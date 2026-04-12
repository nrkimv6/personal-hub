<script lang="ts">
	import { Badge, Button } from '$lib/components/ui';

  import { onMount } from 'svelte';
  import { scheduleApi, bookingApi, itemApi } from '$lib/api';
  import type { ScheduleWithContext } from '$lib/types';

  let schedules: ScheduleWithContext[] = [];
  let loading = true;
  let error: string | null = null;

  // 수정 모달
  let editingSchedule: ScheduleWithContext | null = null;
  let editForm = {
    times: '',
    time_range: '',
    max_bookings_per_schedule: 1,
    is_enabled: true
  };

  // 슬롯 필터링 테스트
  let filterTest = {
    slots: '',
    time_range: '',
    result: null as { filtered_slots: string[]; original_count: number; filtered_count: number } | null
  };

  export async function refresh() {
    await fetchSchedules();
  }

  async function fetchSchedules() {
    loading = true;
    try {
      schedules = await scheduleApi.getActive();
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  function getAutoBookingSchedules() {
    return schedules.filter(s => s.auto_booking_enabled);
  }

  function isScheduleInactive(schedule: ScheduleWithContext) {
    return !schedule.is_enabled ||
           !schedule.business_is_enabled ||
           !schedule.item_is_enabled ||
           schedule.run_status === 'idle';
  }

  function getRunStatusBadge(status: string) {
    switch (status) {
      case 'running': return { class: 'badge-success', label: '실행중' };
      case 'paused': return { class: 'badge-warning', label: '일시정지' };
      case 'queued': return { class: 'badge-info', label: '대기중' };
      case 'error': return { class: 'badge-error', label: '오류' };
      default: return { class: 'badge-gray', label: '유휴' };
    }
  }

  function formatDateTime(dateStr: string | null) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function openEditModal(schedule: ScheduleWithContext) {
    editingSchedule = schedule;
    editForm = {
      times: schedule.times?.join(', ') || '',
      time_range: schedule.time_range || '',
      max_bookings_per_schedule: schedule.max_bookings_per_schedule,
      is_enabled: schedule.is_enabled
    };
  }

  async function handleUpdateSchedule() {
    if (!editingSchedule) return;
    try {
      const times = editForm.times ? editForm.times.split(',').map(t => t.trim()).filter(t => t) : undefined;
      await scheduleApi.update(editingSchedule.id, {
        times: times,
        is_enabled: editForm.is_enabled
      });

      await itemApi.update(editingSchedule.biz_item_pk, {
        time_range: editForm.time_range || undefined,
        max_bookings_per_schedule: editForm.max_bookings_per_schedule
      });

      editingSchedule = null;
      await fetchSchedules();
    } catch (e) {
      alert('수정 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleToggleAutoBooking(schedule: ScheduleWithContext) {
    try {
      await itemApi.update(schedule.biz_item_pk, {
        auto_booking_enabled: !schedule.auto_booking_enabled
      });
      await fetchSchedules();
    } catch (e) {
      alert('변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function handleToggleEnabled(schedule: ScheduleWithContext) {
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

  async function handleResetBookingCount(schedule: ScheduleWithContext) {
    if (!confirm('예약 횟수를 초기화하시겠습니까?')) return;
    try {
      await bookingApi.resetBySchedule(schedule.id);
      await fetchSchedules();
    } catch (e) {
      alert('초기화 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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

  onMount(fetchSchedules);
</script>

<div class="space-y-6">
  <!-- 자동 예약 대상 목록 -->
  <div class="card">
    <div class="flex justify-between items-center mb-4">
      <h3 class="text-lg font-semibold text-foreground">
        자동 예약 대상 ({getAutoBookingSchedules().length})
      </h3>
      <Button variant="secondary" size="sm" onclick={fetchSchedules}>
        새로고침
      </Button>
    </div>

    {#if loading}
      <div class="flex justify-center py-8">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    {:else if error}
      <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
        {error}
      </div>
    {:else if getAutoBookingSchedules().length === 0}
      <p class="text-muted-foreground text-center py-8">
        자동 예약이 활성화된 일정이 없습니다.
      </p>
    {:else}
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-background">
            <tr>
              <th class="px-3 py-2 text-left font-medium text-muted-foreground">대상</th>
              <th class="px-3 py-2 text-left font-medium text-muted-foreground w-24">날짜</th>
              <th class="px-3 py-2 text-left font-medium text-muted-foreground w-20">상태</th>
              <th class="px-3 py-2 text-left font-medium text-muted-foreground w-24">시간범위</th>
              <th class="px-3 py-2 text-left font-medium text-muted-foreground w-20">예약</th>
              <th class="px-3 py-2 text-left font-medium text-muted-foreground w-28">마지막 확인</th>
              <th class="px-3 py-2 text-center font-medium text-muted-foreground w-24">작업</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            {#each getAutoBookingSchedules() as schedule (schedule.id)}
              {@const inactive = isScheduleInactive(schedule)}
              {@const statusBadge = getRunStatusBadge(schedule.run_status)}
              <tr class={inactive ? 'bg-background text-muted-foreground' : ''}>
                <td class="px-3 py-2">
                  <div class="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={schedule.is_enabled}
                      onchange={() => handleToggleEnabled(schedule)}
                      title={schedule.is_enabled ? '비활성화' : '활성화'}
                    />
                    <div>
                      <div class="font-medium {inactive ? 'text-muted-foreground' : 'text-foreground'}">
                        {schedule.business_name}
                      </div>
                      <div class="text-xs {inactive ? 'text-muted-foreground' : 'text-muted-foreground'}">
                        {schedule.item_name}
                        {#if schedule.times && schedule.times.length > 0}
                          <span class="text-muted-foreground">({schedule.times.join(', ')})</span>
                        {/if}
                      </div>
                    </div>
                  </div>
                </td>
                <td class="px-3 py-2 {inactive ? 'text-muted-foreground' : ''}">
                  {schedule.date}
                </td>
                <td class="px-3 py-2">
                  <div class="flex flex-col gap-1">
                    <span class="badge {statusBadge.class}">{statusBadge.label}</span>
                    {#if !schedule.business_is_enabled}
                      <Badge variant="secondary" class="text-xs">업체OFF</Badge>
                    {:else if !schedule.item_is_enabled}
                      <Badge variant="secondary" class="text-xs">아이템OFF</Badge>
                    {/if}
                  </div>
                </td>
                <td class="px-3 py-2 text-xs {inactive ? 'text-muted-foreground' : 'text-muted-foreground'}">
                  {schedule.time_range || '-'}
                </td>
                <td class="px-3 py-2">
                  <span class="font-medium {inactive ? 'text-muted-foreground' : ''}">{schedule.booking_count}</span>
                  <span class="text-muted-foreground">/ {schedule.max_bookings_per_schedule}</span>
                </td>
                <td class="px-3 py-2 text-xs {inactive ? 'text-muted-foreground' : 'text-muted-foreground'}">
                  {formatDateTime(schedule.last_check)}
                </td>
                <td class="px-3 py-2">
                  <div class="flex justify-center gap-1">
                    <Button variant="secondary" size="xs"
                      onclick={() => openEditModal(schedule)}
                      title="수정"
                    >
                      수정
                    </Button>
                    <Button variant="secondary" size="xs"
                      onclick={() => handleResetBookingCount(schedule)}
                      title="예약 횟수 초기화"
                    >
                      0
                    </Button>
                    <Button
                      variant={schedule.auto_booking_enabled ? 'warning' : 'success'}
                      size="xs"
                      onclick={() => handleToggleAutoBooking(schedule)}
                      title={schedule.auto_booking_enabled ? '자동예약 중지' : '자동예약 활성화'}
                    >
                      {schedule.auto_booking_enabled ? '⏸' : '▶'}
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

  <!-- 슬롯 필터링 테스트 -->
  <div class="card">
    <h3 class="text-lg font-semibold text-foreground mb-4">슬롯 필터링 테스트</h3>
    <form onsubmit={(e) => { e.preventDefault(); handleFilterTest(); }} class="space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label for="filter-test-slots" class="block text-sm font-medium text-foreground mb-1">
            슬롯 목록 (한 줄에 하나씩)
          </label>
          <textarea
            id="filter-test-slots"
            class="input h-32"
            bind:value={filterTest.slots}
            required
            placeholder="2025-12-10 18:00:00 (2매)&#10;2025-12-10 19:00:00 (3매)"
          ></textarea>
        </div>
        <div>
          <label for="filter-test-time-range" class="block text-sm font-medium text-foreground mb-1">시간 범위</label>
          <input
            id="filter-test-time-range"
            type="text"
            class="input"
            bind:value={filterTest.time_range}
            required
            placeholder="18:00-21:00"
          />
          <Button type="submit" variant="secondary" class="w-full mt-4">테스트</Button>

          {#if filterTest.result}
            <div class="mt-4 p-3 bg-background rounded-lg text-sm">
              <p class="text-muted-foreground">
                원본: {filterTest.result.original_count}개 → 필터링: {filterTest.result.filtered_count}개
              </p>
              {#if filterTest.result.filtered_slots.length > 0}
                <ul class="mt-2 space-y-1">
                  {#each filterTest.result.filtered_slots as slot}
                    <li class="text-success">{slot}</li>
                  {/each}
                </ul>
              {:else}
                <p class="text-warning-foreground mt-2">조건에 맞는 슬롯이 없습니다.</p>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    </form>
  </div>
</div>

<!-- 수정 모달 -->
{#if editingSchedule}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
      <div class="p-4 border-b">
        <h3 class="text-lg font-semibold">일정 설정 수정</h3>
        <p class="text-sm text-muted-foreground mt-1">
          {editingSchedule.business_name} - {editingSchedule.item_name} ({editingSchedule.date})
        </p>
      </div>
      <form onsubmit={(e) => { e.preventDefault(); handleUpdateSchedule(); }} class="p-4 space-y-4">
        <div>
          <label for="edit-times" class="block text-sm font-medium text-foreground mb-1">
            시간 필터 (쉼표 구분)
          </label>
          <input
            id="edit-times"
            type="text"
            class="input"
            bind:value={editForm.times}
            placeholder="예: 18:00, 19:00, 20:00"
          />
          <p class="text-xs text-muted-foreground mt-1">특정 시간만 모니터링하려면 입력하세요</p>
        </div>
        <div>
          <label for="edit-time-range" class="block text-sm font-medium text-foreground mb-1">
            시간 범위 (자동예약용)
          </label>
          <input
            id="edit-time-range"
            type="text"
            class="input"
            bind:value={editForm.time_range}
            placeholder="예: 18:00-21:00"
          />
          <p class="text-xs text-muted-foreground mt-1">자동예약 시 이 시간대의 슬롯만 예약합니다</p>
        </div>
        <div>
          <label for="edit-max-bookings" class="block text-sm font-medium text-foreground mb-1">
            최대 예약 수
          </label>
          <input
            id="edit-max-bookings"
            type="number"
            class="input"
            bind:value={editForm.max_bookings_per_schedule}
            min="1"
            style="width: 100px;"
          />
        </div>
        <label class="flex items-center gap-2">
          <input type="checkbox" bind:checked={editForm.is_enabled} />
          <span class="text-sm font-medium text-foreground">모니터링 활성화</span>
        </label>
        <div class="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" onclick={() => editingSchedule = null}>
            취소
          </Button>
          <Button type="submit" variant="primary">저장</Button>
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
    font-size: 0.7rem;
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
  .btn-xs {
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
  }
  .btn-warning {
    background-color: #fef3c7;
    color: #92400e;
    border: 1px solid #fcd34d;
  }
  .btn-warning:hover {
    background-color: #fde68a;
  }
</style>
