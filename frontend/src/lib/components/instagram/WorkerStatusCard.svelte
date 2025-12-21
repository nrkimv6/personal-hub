<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { instagramApi } from '$lib/api';
  import type { InstagramWorkerStatus, InstagramWorkerHealth } from '$lib/types';

  let status: InstagramWorkerStatus | null = null;
  let health: InstagramWorkerHealth | null = null;
  let loading = true;
  let error: string | null = null;
  let refreshInterval: ReturnType<typeof setInterval>;

  // 상태별 색상
  function getStatusColor(healthStatus: string | null): string {
    switch (healthStatus) {
      case 'healthy': return 'bg-green-500';
      case 'warning': return 'bg-yellow-500';
      case 'dead': return 'bg-red-500';
      case 'no_worker': return 'bg-gray-400';
      default: return 'bg-gray-400';
    }
  }

  function getStatusText(healthStatus: string | null): string {
    switch (healthStatus) {
      case 'healthy': return '활성';
      case 'warning': return '경고';
      case 'dead': return '중지';
      case 'no_worker': return '없음';
      default: return '알 수 없음';
    }
  }

  function getStateText(state: string | null): string {
    switch (state) {
      case 'idle': return '대기';
      case 'crawling': return '크롤링 중';
      case 'processing': return '처리 중';
      case 'stopped': return '중지됨';
      default: return '-';
    }
  }

  function formatUptime(seconds: number): string {
    if (seconds < 60) return `${seconds}초`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}분`;
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}시간 ${mins}분`;
  }

  function formatAge(seconds: number): string {
    if (seconds < 60) return `${seconds}초 전`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
    return `${Math.floor(seconds / 3600)}시간 전`;
  }

  async function fetchData() {
    try {
      const [statusData, healthData] = await Promise.all([
        instagramApi.getWorkerStatus(),
        instagramApi.getWorkerHealth()
      ]);
      status = statusData;
      health = healthData;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    fetchData();
    // 5초마다 새로고침
    refreshInterval = setInterval(fetchData, 5000);
  });

  onDestroy(() => {
    if (refreshInterval) clearInterval(refreshInterval);
  });
</script>

<div class="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
  <div class="flex items-center justify-between mb-3">
    <h3 class="text-sm font-medium text-gray-700 dark:text-gray-300">워커 상태</h3>
    {#if health}
      <span class="inline-flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-full {getStatusColor(health.status)}"></span>
        <span class="text-sm font-medium {health.status === 'healthy' ? 'text-green-600' : health.status === 'warning' ? 'text-yellow-600' : 'text-gray-500'}">
          {getStatusText(health.status)}
        </span>
      </span>
    {/if}
  </div>

  {#if loading}
    <div class="animate-pulse space-y-2">
      <div class="h-4 bg-gray-200 rounded w-3/4"></div>
      <div class="h-4 bg-gray-200 rounded w-1/2"></div>
    </div>
  {:else if error}
    <p class="text-sm text-red-500">{error}</p>
  {:else if !status}
    <p class="text-sm text-gray-500 dark:text-gray-400">워커가 실행 중이 아닙니다</p>
  {:else}
    <div class="space-y-2 text-sm">
      <div class="flex justify-between">
        <span class="text-gray-500">PID</span>
        <span class="text-gray-900 dark:text-gray-100 font-mono">{status.pid || '-'}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">Uptime</span>
        <span class="text-gray-900 dark:text-gray-100">{formatUptime(status.uptime_seconds)}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">Heartbeat</span>
        <span class="text-gray-900 dark:text-gray-100">{formatAge(status.heartbeat_age_seconds)}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-gray-500">상태</span>
        <span class="text-gray-900 dark:text-gray-100">
          {getStateText(status.current_state)}
          {#if status.current_account}
            <span class="text-blue-500">(@{status.current_account})</span>
          {/if}
        </span>
      </div>
    </div>
  {/if}
</div>
