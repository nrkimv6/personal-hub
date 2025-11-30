<script lang="ts">
  import { onMount } from 'svelte';
  import { notificationApi, systemApi } from '$lib/api';
  import type { NotificationSettings, QueueItem } from '$lib/types';

  let notificationSettings: NotificationSettings | null = null;
  let queue: QueueItem[] = [];
  let loading = true;
  let saving = false;
  let error: string | null = null;

  const notifyStateOptions = [
    { value: 'available', label: '예약 가능 발견' },
    { value: 'booking_success', label: '예약 성공' },
    { value: 'booking_failed', label: '예약 실패' },
    { value: 'error', label: '오류 발생' },
    { value: 'startup', label: '서버 시작' }
  ];

  async function fetchData() {
    loading = true;
    try {
      const [settings, queueData] = await Promise.all([
        notificationApi.getSettings(),
        systemApi.queue()
      ]);
      notificationSettings = settings;
      queue = queueData;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  async function saveNotificationSettings() {
    if (!notificationSettings) return;
    saving = true;
    try {
      await notificationApi.updateSettings(notificationSettings);
      alert('설정이 저장되었습니다.');
    } catch (e) {
      alert('저장 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    } finally {
      saving = false;
    }
  }

  function toggleNotifyState(state: string) {
    if (!notificationSettings) return;
    const index = notificationSettings.notify_states.indexOf(state);
    if (index >= 0) {
      notificationSettings.notify_states = notificationSettings.notify_states.filter(s => s !== state);
    } else {
      notificationSettings.notify_states = [...notificationSettings.notify_states, state];
    }
  }

  async function handleClearQueue() {
    if (!confirm('대기열을 비우시겠습니까?')) return;
    try {
      const result = await systemApi.clearQueue();
      alert(`${result.cleared_count}개 항목이 삭제되었습니다.`);
      await fetchData();
    } catch (e) {
      alert('실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  onMount(fetchData);
</script>

<div class="p-6">
  <div class="mb-6">
    <h2 class="text-2xl font-bold text-gray-900">설정</h2>
  </div>

  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else}
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 알림 설정 -->
      <div class="card">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">알림 설정</h3>

        {#if notificationSettings}
          <div class="space-y-4">
            <div class="flex items-center justify-between">
              <div>
                <p class="font-medium">텔레그램 알림</p>
                <p class="text-sm text-gray-500">텔레그램으로 알림을 받습니다.</p>
              </div>
              <label class="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  class="sr-only peer"
                  bind:checked={notificationSettings.enable_telegram}
                />
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>

            <div class="flex items-center justify-between">
              <div>
                <p class="font-medium">데스크톱 알림</p>
                <p class="text-sm text-gray-500">시스템 알림을 표시합니다.</p>
              </div>
              <label class="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  class="sr-only peer"
                  bind:checked={notificationSettings.enable_desktop}
                />
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>

            <hr />

            <div>
              <p class="font-medium mb-2">알림 받을 상태</p>
              <div class="space-y-2">
                {#each notifyStateOptions as option}
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={notificationSettings.notify_states.includes(option.value)}
                      on:change={() => toggleNotifyState(option.value)}
                      class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span class="text-sm">{option.label}</span>
                  </label>
                {/each}
              </div>
            </div>

            <button
              class="btn btn-primary w-full"
              on:click={saveNotificationSettings}
              disabled={saving}
            >
              {saving ? '저장 중...' : '💾 설정 저장'}
            </button>
          </div>
        {/if}
      </div>

      <!-- 대기열 관리 -->
      <div class="card">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-lg font-semibold text-gray-900">대기열</h3>
          <div class="flex gap-2">
            <button class="btn btn-secondary btn-sm" on:click={fetchData}>
              🔄 새로고침
            </button>
            {#if queue.length > 0}
              <button class="btn btn-danger btn-sm" on:click={handleClearQueue}>
                🗑️ 비우기
              </button>
            {/if}
          </div>
        </div>

        {#if queue.length === 0}
          <div class="text-center text-gray-500 py-8">
            대기열이 비어있습니다.
          </div>
        {:else}
          <div class="space-y-2 max-h-96 overflow-y-auto">
            {#each queue as item (item.position)}
              <div class="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                <span class="w-8 h-8 flex items-center justify-center bg-blue-100 text-blue-800 rounded-full font-medium text-sm">
                  {item.position}
                </span>
                <div class="flex-1 min-w-0">
                  <p class="font-medium truncate">{item.label}</p>
                  <p class="text-sm text-gray-500 truncate">{item.url}</p>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    <!-- API 문서 링크 -->
    <div class="card mt-6">
      <h3 class="text-lg font-semibold text-gray-900 mb-4">API 문서</h3>
      <div class="flex gap-4">
        <a
          href="/docs"
          target="_blank"
          class="btn btn-secondary"
        >
          📖 Swagger UI
        </a>
        <a
          href="/redoc"
          target="_blank"
          class="btn btn-secondary"
        >
          📚 ReDoc
        </a>
      </div>
    </div>
  {/if}
</div>
