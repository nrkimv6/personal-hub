<script lang="ts">
  /**
   * 통합 TabNav 컴포넌트
   * - variant='primary': 언더라인 스타일 (기존 PrimaryTabNav)
   * - variant='secondary': 배경색 스타일 (기존 SecondaryTabNav)
   * - variant='underline': 간단한 언더라인 스타일
   */
  import { page } from '$app/stores';

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
  }

  let { tabs, activeTab = $bindable(), variant = 'primary', urlBased = false }: Props = $props();

  const primaryStyles = {
    active: 'border-primary text-primary dark:text-blue-400',
    inactive: 'border-transparent text-secondary hover:text-primary hover:border-gray-300',
  };

  const secondaryStyles = {
    active: 'bg-card dark:bg-gray-700 text-primary dark:text-white shadow-sm',
    inactive: 'text-secondary dark:text-gray-400 hover:text-primary',
  };

  const underlineStyles = {
    active: 'border-primary text-primary',
    inactive: 'border-transparent text-secondary hover:text-primary',
  };

  function getStyles(isActive: boolean) {
    if (variant === 'secondary') {
      return isActive ? secondaryStyles.active : secondaryStyles.inactive;
    }
    if (variant === 'underline') {
      return isActive ? underlineStyles.active : underlineStyles.inactive;
    }
    return isActive ? primaryStyles.active : primaryStyles.inactive;
  }

  function isActive(tab: Tab): boolean {
    if (urlBased && tab.href) {
      return $page.url.pathname === tab.href;
    }
    return activeTab === tab.id;
  }
</script>

{#if variant === 'secondary'}
  <div class="bg-page dark:bg-gray-800 rounded-lg p-1 mb-4 inline-flex">
    {#each tabs as tab}
      {#if urlBased && tab.href}
        <a
          href={tab.href}
          class="py-1.5 px-3 rounded-md text-sm font-medium transition-colors {getStyles(isActive(tab))}"
        >
          {#if tab.icon}<span class="mr-1">{tab.icon}</span>{/if}
          {tab.label}
          {#if tab.count !== undefined}
            <span class="ml-1 text-xs bg-gray-200 dark:bg-gray-600 px-1.5 py-0.5 rounded-full">{tab.count}</span>
          {/if}
        </a>
      {:else}
        <button
          onclick={() => activeTab = tab.id}
          class="py-1.5 px-3 rounded-md text-sm font-medium transition-colors {getStyles(isActive(tab))}"
        >
          {#if tab.icon}<span class="mr-1">{tab.icon}</span>{/if}
          {tab.label}
          {#if tab.count !== undefined}
            <span class="ml-1 text-xs bg-gray-200 dark:bg-gray-600 px-1.5 py-0.5 rounded-full">{tab.count}</span>
          {/if}
        </button>
      {/if}
    {/each}
  </div>
{:else}
  <div class="border-b border-border dark:border-gray-700 mb-4">
    <nav class="flex space-x-1" aria-label="Tabs">
      {#each tabs as tab}
        {#if urlBased && tab.href}
          <a
            href={tab.href}
            class="py-3 px-5 border-b-2 font-medium text-base transition-colors {getStyles(isActive(tab))}"
          >
            {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
            {tab.label}
            {#if tab.count !== undefined}
              <span class="ml-1 text-xs bg-gray-100 dark:bg-gray-600 px-1.5 py-0.5 rounded-full">{tab.count}</span>
            {/if}
          </a>
        {:else}
          <button
            onclick={() => activeTab = tab.id}
            class="py-3 px-5 border-b-2 font-medium text-base transition-colors {getStyles(isActive(tab))}"
          >
            {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
            {tab.label}
            {#if tab.count !== undefined}
              <span class="ml-1 text-xs bg-gray-100 dark:bg-gray-600 px-1.5 py-0.5 rounded-full">{tab.count}</span>
            {/if}
          </button>
        {/if}
      {/each}
    </nav>
  </div>
{/if}
