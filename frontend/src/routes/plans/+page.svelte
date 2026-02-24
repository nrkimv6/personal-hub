<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import PlanListTab from './PlanListTab.svelte';
  import ArchiveTab from './ArchiveTab.svelte';
  import HistoryTab from './HistoryTab.svelte';

  type Tab = 'plans' | 'archive' | 'history';

  let activeTab: Tab = 'plans';

  $: {
    const tabParam = $page.url.searchParams.get('tab') as Tab | null;
    activeTab = tabParam && ['plans', 'archive', 'history'].includes(tabParam) ? tabParam : 'plans';
  }

  function setTab(tab: Tab) {
    const url = new URL(window.location.href);
    if (tab === 'plans') {
      url.searchParams.delete('tab');
    } else {
      url.searchParams.set('tab', tab);
    }
    goto(url.toString(), { replaceState: true, noScroll: true });
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'plans', label: '계획서 목록' },
    { id: 'archive', label: '아카이브' },
    { id: 'history', label: '이벤트 이력' },
  ];
</script>

<div class="flex flex-col h-full p-4 gap-4 bg-background">
  <!-- 헤더 -->
  <div class="flex items-center justify-between">
    <h1 class="text-lg font-bold text-foreground">계획서 관리</h1>
  </div>

  <!-- 탭 -->
  <div class="flex gap-1 border-b border-border">
    {#each tabs as tab}
      <button
        class="px-4 py-2 text-sm transition-colors {activeTab === tab.id
          ? 'text-primary border-b-2 border-primary font-medium'
          : 'text-muted-foreground hover:text-foreground'}"
        on:click={() => setTab(tab.id)}
      >
        {tab.label}
      </button>
    {/each}
  </div>

  <!-- 탭 컨텐츠 -->
  <div class="flex-1 min-h-0 overflow-hidden">
    {#if activeTab === 'plans'}
      <PlanListTab />
    {:else if activeTab === 'archive'}
      <ArchiveTab />
    {:else if activeTab === 'history'}
      <HistoryTab />
    {/if}
  </div>
</div>
