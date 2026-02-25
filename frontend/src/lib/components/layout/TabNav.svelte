<script lang="ts">
  /**
   * 통합 TabNav 컴포넌트
   * - variant='primary': 언더라인 스타일 (기존 PrimaryTabNav)
   * - variant='secondary': 배경색 스타일 (기존 SecondaryTabNav)
   * - variant='underline': 간단한 언더라인 스타일
   * - queryParam: URL 쿼리파라미터 동기화 (예: 'tab' → ?tab=gallery)
   * - urlBased: URL pathname 기반 활성 탭 판단
   * - replaceState: goto() 호출 시 히스토리 교체 여부 (기본 true)
   * - size: 'default' | 'compact' — compact일 때 py-2 px-3 text-sm 적용
   */
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';

  type Tab = {
    id: string;
    label: string;
    href?: string;
    icon?: string;
    count?: number;
    color?: string;
    countVariant?: 'default' | 'error' | 'warning';
    exact?: boolean;
  };

  interface Props {
    tabs: Tab[];
    activeTab?: string;
    variant?: 'primary' | 'secondary' | 'underline';
    urlBased?: boolean;
    queryParam?: string;
    replaceState?: boolean;
    size?: 'default' | 'compact';
  }

  let {
    tabs,
    activeTab = $bindable(),
    variant = 'primary',
    urlBased = false,
    queryParam,
    replaceState = true,
    size = 'default',
  }: Props = $props();

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

  function getStyles(active: boolean, tab: Tab) {
    // color prop이 있고 활성 상태면 동적 스타일 반환
    if (active && tab.color && variant !== 'secondary') {
      return `border-b-2 text-[${tab.color}] border-[${tab.color}]`;
    }
    if (variant === 'secondary') {
      return active ? secondaryStyles.active : secondaryStyles.inactive;
    }
    if (variant === 'underline') {
      return active ? underlineStyles.active : underlineStyles.inactive;
    }
    return active ? primaryStyles.active : primaryStyles.inactive;
  }

  function getCountStyles(tab: Tab): string {
    if (tab.countVariant === 'error') {
      return 'ml-1 text-xs bg-destructive/10 text-destructive px-1.5 py-0.5 rounded-full';
    }
    if (tab.countVariant === 'warning') {
      return 'ml-1 text-xs bg-yellow-500/10 text-yellow-600 px-1.5 py-0.5 rounded-full';
    }
    if (variant === 'secondary') {
      return 'ml-1 text-xs bg-secondary px-1.5 py-0.5 rounded-full';
    }
    return 'ml-1 text-xs bg-muted px-1.5 py-0.5 rounded-full';
  }

  function isTabActive(tab: Tab): boolean {
    if (queryParam) {
      const paramValue = $page.url.searchParams.get(queryParam);
      return (paramValue || tabs[0]?.id) === tab.id;
    }
    if (urlBased && tab.href) {
      if (tab.exact) {
        return $page.url.pathname === tab.href;
      }
      return $page.url.pathname.startsWith(tab.href);
    }
    return activeTab === tab.id;
  }

  function handleTabClick(tab: Tab) {
    if (queryParam) {
      goto(`${$page.url.pathname}?${queryParam}=${tab.id}`, { replaceState });
    } else {
      activeTab = tab.id;
    }
  }

  // size별 탭 패딩/폰트 클래스
  const sizeClass = size === 'compact' ? 'py-2 px-3 text-sm' : 'py-3 px-5 text-base';
</script>

{#if variant === 'secondary'}
  <div class="bg-muted rounded-lg p-1 mb-4 inline-flex">
    {#each tabs as tab}
      {#if urlBased && tab.href}
        <a
          href={tab.href}
          data-sveltekit-preload-data
          class="py-1.5 px-3 rounded-md text-sm font-medium transition-colors {getStyles(isTabActive(tab), tab)}"
        >
          {#if tab.icon}<span class="mr-1">{tab.icon}</span>{/if}
          {tab.label}
          {#if tab.count !== undefined}
            <span class={getCountStyles(tab)}>{tab.count}</span>
          {/if}
        </a>
      {:else}
        <button
          onclick={() => handleTabClick(tab)}
          class="py-1.5 px-3 rounded-md text-sm font-medium transition-colors {getStyles(isTabActive(tab), tab)}"
        >
          {#if tab.icon}<span class="mr-1">{tab.icon}</span>{/if}
          {tab.label}
          {#if tab.count !== undefined}
            <span class={getCountStyles(tab)}>{tab.count}</span>
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
            data-sveltekit-preload-data
            class="{sizeClass} border-b-2 font-medium transition-colors {getStyles(isTabActive(tab), tab)}"
          >
            {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
            {tab.label}
            {#if tab.count !== undefined}
              <span class={getCountStyles(tab)}>{tab.count}</span>
            {/if}
          </a>
        {:else}
          <button
            onclick={() => handleTabClick(tab)}
            class="{sizeClass} border-b-2 font-medium transition-colors {getStyles(isTabActive(tab), tab)}"
          >
            {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
            {tab.label}
            {#if tab.count !== undefined}
              <span class={getCountStyles(tab)}>{tab.count}</span>
            {/if}
          </button>
        {/if}
      {/each}
    </nav>
  </div>
{/if}
