<script lang="ts">
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import ServiceStatusTab from './ServiceStatusTab.svelte';
  import ErrorLogTab from './ErrorLogTab.svelte';
  import IntegrityTab from './IntegrityTab.svelte';
  import BrowsersTab from './BrowsersTab.svelte';
  import SettingsTab from './SettingsTab.svelte';
  import DiagnosticTab from './DiagnosticTab.svelte';
  import MemoryTab from './MemoryTab.svelte';
  import SleepNowTab from './SleepNowTab.svelte';

  // 탭 정의
  type TabId = 'status' | 'errors' | 'integrity' | 'browsers' | 'settings' | 'memory' | 'diagnostic' | 'sleep-now';

  // 탭 상태
  let activeTab: TabId = $state('status');

  // 배지 상태
  let serviceStatus = $state<{ running: number; total: number } | null>(null);
  let unresolvedErrors = $state<number | null>(null);
  let integrityIssues = $state<number | null>(null);
  let memoryDangerLevel = $state<'normal' | 'warning' | 'critical'>('normal');

  // 동적 탭 목록 (배지 포함)
  const systemTabs = $derived([
    {
      id: 'status',
      label: '서비스 상태',
      count: serviceStatus ? serviceStatus.running : undefined,
    },
    {
      id: 'errors',
      label: '에러 로그',
      count: unresolvedErrors ?? undefined,
      countVariant: 'error' as const,
    },
    {
      id: 'integrity',
      label: '데이터 정합성',
      count: integrityIssues ?? undefined,
      countVariant: 'warning' as const,
    },
    { id: 'browsers', label: '브라우저/프록시' },
    { id: 'settings', label: '설정' },
    {
      id: 'memory',
      label: '메모리',
      countVariant: memoryDangerLevel === 'critical' ? ('error' as const) : memoryDangerLevel === 'warning' ? ('warning' as const) : undefined,
    },
    { id: 'diagnostic', label: '진단' },
    { id: 'sleep-now', label: 'Sleep Now' },
  ]);

  // 콜백 함수들
  function handleServiceStatusChange(running: number, total: number) {
    serviceStatus = { running, total };
  }

  function handleUnresolvedChange(count: number) {
    unresolvedErrors = count;
  }

  function handleIssueCountChange(count: number) {
    integrityIssues = count;
  }

  function handleMemoryDangerChange(level: string) {
    memoryDangerLevel = level as 'normal' | 'warning' | 'critical';
  }
</script>

<svelte:head>
  <title>시스템 / 설정 | Monitor Page</title>
</svelte:head>

<div class="p-6 space-y-6">
  <!-- 헤더 -->
  <PageHeader title="시스템 / 설정" subtitle="서비스 상태, 오류 로그, 시스템 설정을 관리합니다" />

  <!-- 탭 네비게이션 -->
  <TabNav tabs={systemTabs} bind:activeTab variant="primary" queryParam="tab" replaceState={false} />

  <!-- 탭 컨텐츠 -->
  <div class="mt-4">
    {#if activeTab === 'status'}
      <ServiceStatusTab onStatusChange={handleServiceStatusChange} />
    {:else if activeTab === 'errors'}
      <ErrorLogTab onUnresolvedChange={handleUnresolvedChange} />
    {:else if activeTab === 'integrity'}
      <IntegrityTab onIssueCountChange={handleIssueCountChange} />
    {:else if activeTab === 'browsers'}
      <BrowsersTab />
    {:else if activeTab === 'settings'}
      <SettingsTab />
    {:else if activeTab === 'memory'}
      <MemoryTab onDangerChange={handleMemoryDangerChange} />
    {:else if activeTab === 'diagnostic'}
      <DiagnosticTab />
    {:else if activeTab === 'sleep-now'}
      <SleepNowTab />
    {/if}
  </div>
</div>
