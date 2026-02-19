<script lang="ts">
  /**
   * 통합 TabNav 컴포넌트
   * - variant='primary': 언더라인 스타일 (기존 PrimaryTabNav)
   * - variant='secondary': 배경색 스타일 (기존 SecondaryTabNav)
   * - variant='underline': 간단한 언더라인 스타일
   * - queryParam: URL 쿼리파라미터 동기화 (예: 'tab' → ?tab=gallery)
   */
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';

  type Tab = {
    id: string;
    label: string;
    href?: string;
    icon?: string;
    count?: number;
  };

  interface Props {
    tabs: Tab[];
    activeTab?: string;
    variant?: 'primary' | 'secondary' | 'underline';
    urlBased?: boolean;
    queryParam?: string;
  }

  let { tabs, activeTab = $bindable(), variant = 'primary', urlBased = false, queryParam }: Props = $props();

  // queryParam 모드: URL searchParams → activeTab 양방향 동기화
  $effect(() => {
    if (queryParam) {
      const paramValue = $page.url.searchParams.get(queryParam);
      activeTab = paramValue || tabs[0]?.id;
    }
  });

  const primaryStyles = {
    active: 'border-primary text-primary',
    inactive: 'border-transparent text-muted-foreground hover:text-primary hover:border-muted',
  };

  const secondaryStyles = {
    active: 'bg-card text-primary shadow-sm',
    inactive: 'text-muted-foreground hover:text-primary',
  };

  const underlineStyles = {
    active: 'border-primary text-primary',
    inactive: 'border-transparent text-muted-foreground hover:text-primary',
  };

  function getStyles(active: boolean) {
    if (variant === 'secondary') {
      return active ? secondaryStyles.active : secondaryStyles.inactive;
    }
    if (variant === 'underline') {
      return active ? underlineStyles.active : underlineStyles.inactive;
    }
    return active ? primaryStyles.active : primaryStyles.inactive;
  }

  function isTabActive(tab: Tab): boolean {
    if (queryParam) {
      const paramValue = $page.url.searchParams.get(queryParam);
      return (paramValue || tabs[0]?.id) === tab.id;
    }
    if (urlBased && tab.href) {
      return $page.url.pathname === tab.href;
    }
    return activeTab === tab.id;
  }

  function handleTabClick(tab: Tab) {
    if (queryParam) {
      goto(`${$page.url.pathname}?${queryParam}=${tab.id}`, { replaceState: true });
    } else {
      activeTab = tab.id;
    }
  }
</script>

{#if variant === 'secondary'}
  <div class="bg-muted rounded-lg p-1 mb-4 inline-flex">
    {#each tabs as tab}
      {#if urlBased && tab.href}
        <a
          href={tab.href}
          class="py-1.5 px-3 rounded-md text-sm font-medium transition-colors {getStyles(isTabActive(tab))}"
        >
          {#if tab.icon}<span class="mr-1">{tab.icon}</span>{/if}
          {tab.label}
          {#if tab.count !== undefined}
            <span class="ml-1 text-xs bg-secondary px-1.5 py-0.5 rounded-full">{tab.count}</span>
          {/if}
        </a>
      {:else}
        <button
          onclick={() => handleTabClick(tab)}
          class="py-1.5 px-3 rounded-md text-sm font-medium transition-colors {getStyles(isTabActive(tab))}"
        >
          {#if tab.icon}<span class="mr-1">{tab.icon}</span>{/if}
          {tab.label}
          {#if tab.count !== undefined}
            <span class="ml-1 text-xs bg-secondary px-1.5 py-0.5 rounded-full">{tab.count}</span>
          {/if}
        </button>
      {/if}
    {/each}
  </div>
{:else}
  <div class="border-b border-border mb-4">
    <nav class="flex space-x-1" aria-label="Tabs">
      {#each tabs as tab}
        {#if urlBased && tab.href}
          <a
            href={tab.href}
            class="py-3 px-5 border-b-2 font-medium text-base transition-colors {getStyles(isTabActive(tab))}"
          >
            {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
            {tab.label}
            {#if tab.count !== undefined}
              <span class="ml-1 text-xs bg-muted px-1.5 py-0.5 rounded-full">{tab.count}</span>
            {/if}
          </a>
        {:else}
          <button
            onclick={() => handleTabClick(tab)}
            class="py-3 px-5 border-b-2 font-medium text-base transition-colors {getStyles(isTabActive(tab))}"
          >
            {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
            {tab.label}
            {#if tab.count !== undefined}
              <span class="ml-1 text-xs bg-muted px-1.5 py-0.5 rounded-full">{tab.count}</span>
            {/if}
          </button>
        {/if}
      {/each}
    </nav>
  </div>
{/if}
