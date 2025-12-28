<script lang="ts">
  import { onMount } from 'svelte';
  import { dashboardApi } from '$lib/api';
  import type { UnifiedDashboard } from '$lib/types';
  import ServiceHealthCard from './ServiceHealthCard.svelte';
  import SystemResourceCard from './SystemResourceCard.svelte';
  import MonitoringStatsCard from './MonitoringStatsCard.svelte';
  import InstagramSummaryCard from './InstagramSummaryCard.svelte';
  import RecentAlertsCard from './RecentAlertsCard.svelte';

  let data = $state<UnifiedDashboard | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastUpdated = $state<Date | null>(null);

  const REFRESH_INTERVAL = 10000; // 10초

  async function fetchData() {
    try {
      data = await dashboardApi.unified();
      error = null;
      lastUpdated = new Date();
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  });
</script>

<svelte:head>
  <title>통합 대시보드</title>
</svelte:head>

<div class="p-6 space-y-6">
  <!-- 헤더 -->
  <div class="flex justify-between items-center">
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white">통합 대시보드</h1>
    <div class="flex items-center gap-4">
      {#if lastUpdated}
        <span class="text-sm text-gray-500 dark:text-gray-400">
          마지막 업데이트: {lastUpdated.toLocaleTimeString()}
        </span>
      {/if}
      <span class="text-xs text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
        10초 자동 새로고침
      </span>
    </div>
  </div>

  {#if loading}
    <div class="text-center py-20">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
      <p class="mt-4 text-gray-500 dark:text-gray-400">로딩 중...</p>
    </div>
  {:else if error}
    <div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
      <p class="text-red-600 dark:text-red-400">{error}</p>
      <button
        onclick={fetchData}
        class="mt-2 text-sm text-red-700 dark:text-red-300 underline hover:no-underline"
      >
        다시 시도
      </button>
    </div>
  {:else if data}
    <!-- 서비스 상태 (전체 너비) -->
    <ServiceHealthCard health={data.service_health} />

    <!-- 3칸 그리드 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
      <SystemResourceCard resource={data.system_resource} />
      <MonitoringStatsCard stats={data.monitoring_stats} />
      <InstagramSummaryCard summary={data.instagram_summary} />
    </div>

    <!-- 최근 알림 -->
    <RecentAlertsCard alerts={data.recent_alerts} />
  {/if}
</div>
