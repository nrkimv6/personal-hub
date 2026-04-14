<script lang="ts">
  import { onMount } from 'svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import { dashboardApi } from '$lib/api';
  import { waitForApiReady } from '$lib/api/system';
  import { ApiConnectionError } from '$lib/api/client';
  import type { UnifiedDashboard } from '$lib/types';
  import ServiceHealthCard from './ServiceHealthCard.svelte';
  import SystemResourceCard from './SystemResourceCard.svelte';
  import MonitoringStatsCard from './MonitoringStatsCard.svelte';
  import InstagramSummaryCard from './InstagramSummaryCard.svelte';
  import RecentAlertsCard from './RecentAlertsCard.svelte';

  let data = $state<UnifiedDashboard | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let isConnectionError = $state(false);
  let lastUpdated = $state<Date | null>(null);

  const REFRESH_INTERVAL = 10000; // 10초

  async function fetchData() {
    try {
      data = await dashboardApi.unified();
      error = null;
      isConnectionError = false;
      lastUpdated = new Date();
    } catch (e) {
      if (e instanceof ApiConnectionError) {
        isConnectionError = true;
        error = 'API 서버에 연결할 수 없습니다';
      } else {
        isConnectionError = false;
        error = e instanceof Error ? e.message : '데이터 로드 실패';
      }
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    let interval: ReturnType<typeof setInterval> | null = null;

    // API startup 완료 대기 후 데이터 요청 (콜드 스타트 대응)
    void (async () => {
      await waitForApiReady();
      fetchData();
      interval = setInterval(fetchData, REFRESH_INTERVAL);
    })();

    return () => {
      if (interval) clearInterval(interval);
    };
  });
</script>

<svelte:head>
  <title>통합 대시보드</title>
</svelte:head>

<div class="p-6 space-y-6">
  <!-- 헤더 -->
  <PageHeader title="통합 대시보드" subtitle="서비스 상태와 모니터링 현황을 한눈에 확인합니다">
    <div class="flex items-center gap-4">
      {#if lastUpdated}
        <span class="text-sm text-muted-foreground">
          마지막 업데이트: {lastUpdated.toLocaleTimeString()}
        </span>
      {/if}
      <span class="text-xs text-muted-foreground bg-muted px-2 py-1 rounded">
        10초 자동 새로고침
      </span>
    </div>
  </PageHeader>

  {#if loading}
    <div class="text-center py-20">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
      <p class="mt-4 text-muted-foreground dark:text-muted-foreground">로딩 중...</p>
    </div>
  {:else if error}
    <div class="bg-error-light dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
      <p class="text-error dark:text-red-400 font-medium">{error}</p>

      {#if isConnectionError}
        <div class="mt-3 p-3 bg-warning-light dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded">
          <p class="text-sm font-medium text-warning-foreground dark:text-yellow-200">좀비 포트 가능성</p>
          <p class="text-xs text-warning-foreground dark:text-yellow-300 mt-1">
            서버가 비정상 종료되어 포트가 점유된 상태일 수 있습니다.
          </p>
          <div class="mt-2 text-xs text-warning-foreground dark:text-yellow-400 space-y-1">
            <p class="font-medium">해결 방법:</p>
            <p>1. 관리자 권한으로 실행: <code class="bg-warning-light dark:bg-yellow-800 px-1 rounded">net stop winnat && net start winnat</code></p>
            <p>2. 위 방법이 안 되면 시스템 재부팅</p>
          </div>
        </div>
      {/if}

      <button
        onclick={fetchData}
        class="mt-3 text-sm text-error dark:text-red-300 underline hover:no-underline"
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
