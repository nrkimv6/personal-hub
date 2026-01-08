<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import ServiceStatusTab from './ServiceStatusTab.svelte';
  import ErrorLogTab from './ErrorLogTab.svelte';
  import IntegrityTab from './IntegrityTab.svelte';

  // 탭 정의
  type TabId = 'status' | 'errors' | 'integrity';

  interface Tab {
    id: TabId;
    label: string;
    icon: string;
  }

  const tabs: Tab[] = [
    { id: 'status', label: '서비스 상태', icon: '🖥️' },
    { id: 'errors', label: '에러 로그', icon: '⚠️' },
    { id: 'integrity', label: '데이터 정합성', icon: '🔍' }
  ];

  // 배지 상태
  let serviceStatus = $state<{ running: number; total: number } | null>(null);
  let unresolvedErrors = $state<number | null>(null);
  let integrityIssues = $state<number | null>(null);

  // URL 파라미터에서 탭 읽기
  let activeTab = $derived.by((): TabId => {
    const tabParam = $page.url.searchParams.get('tab');
    if (tabParam === 'errors' || tabParam === 'integrity') {
      return tabParam;
    }
    return 'status';
  });

  // 탭 변경 함수
  function setTab(tabId: TabId) {
    const url = new URL($page.url);
    if (tabId === 'status') {
      url.searchParams.delete('tab');
    } else {
      url.searchParams.set('tab', tabId);
    }
    goto(url.toString(), { replaceState: false, keepFocus: true });
  }

  // 배지 렌더링
  function getTabBadge(tabId: TabId): string | null {
    switch (tabId) {
      case 'status':
        if (serviceStatus) {
          return `${serviceStatus.running}/${serviceStatus.total}`;
        }
        return null;
      case 'errors':
        if (unresolvedErrors !== null && unresolvedErrors > 0) {
          return unresolvedErrors.toString();
        }
        return null;
      case 'integrity':
        if (integrityIssues !== null && integrityIssues > 0) {
          return integrityIssues.toString();
        }
        return null;
      default:
        return null;
    }
  }

  function getBadgeClass(tabId: TabId): string {
    switch (tabId) {
      case 'errors':
        return 'bg-red-500 text-white';
      case 'integrity':
        return 'bg-yellow-500 text-white';
      default:
        return 'bg-secondary text-foreground dark:bg-gray-600 dark:text-gray-200';
    }
  }

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
</script>

<svelte:head>
  <title>시스템 현황</title>
</svelte:head>

<div class="p-6 space-y-6">
  <!-- 헤더 -->
  <div class="flex justify-between items-center">
    <h1 class="text-2xl font-bold text-foreground dark:text-white">시스템 현황</h1>
  </div>

  <!-- 탭 네비게이션 -->
  <div class="border-b border-border dark:border-gray-700">
    <nav class="flex gap-4" aria-label="Tabs">
      {#each tabs as tab}
        {@const isActive = activeTab === tab.id}
        {@const badge = getTabBadge(tab.id)}
        <button
          onclick={() => setTab(tab.id)}
          class="flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors
            {isActive
              ? 'border-blue-500 text-blue-600 dark:text-blue-400'
              : 'border-transparent text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-gray-300 hover:border-border dark:hover:border-gray-600'}"
          aria-current={isActive ? 'page' : undefined}
        >
          <span>{tab.icon}</span>
          <span>{tab.label}</span>
          {#if badge}
            <span class="px-2 py-0.5 text-xs rounded-full {getBadgeClass(tab.id)}">
              {badge}
            </span>
          {/if}
        </button>
      {/each}
    </nav>
  </div>

  <!-- 탭 컨텐츠 -->
  <div class="mt-4">
    {#if activeTab === 'status'}
      <ServiceStatusTab onStatusChange={handleServiceStatusChange} />
    {:else if activeTab === 'errors'}
      <ErrorLogTab onUnresolvedChange={handleUnresolvedChange} />
    {:else if activeTab === 'integrity'}
      <IntegrityTab onIssueCountChange={handleIssueCountChange} />
    {/if}
  </div>
</div>
