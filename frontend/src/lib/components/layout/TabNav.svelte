<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import type { Component, ComponentType } from 'svelte';

  export type TabItem = {
    id: string;
    label: string;
    shortLabel?: string;
    href?: string;
    icon?: string | Component | ComponentType;
    count?: number;
    color?: string;
    countVariant?: 'default' | 'error' | 'warning';
    exact?: boolean;
  };

  interface Props {
    tabs: TabItem[];
    activeTab?: string;
    variant?: 'primary' | 'secondary' | 'underline';
    level?: 'primary' | 'secondary';
    urlBased?: boolean;
    queryParam?: string;
    replaceState?: boolean;
    size?: 'default' | 'compact';
    sticky?: boolean;
    overflow?: 'scroll' | 'wrap';
    onTabChange?: (tabId: string) => void;
  }

  let {
    tabs,
    activeTab = $bindable(),
    variant = 'primary',
    level = 'primary',
    urlBased = false,
    queryParam,
    replaceState = true,
    size = 'default',
    sticky = false,
    overflow = 'scroll',
    onTabChange,
  }: Props = $props();

  $effect(() => {
    if (!queryParam) return;
    const paramValue = $page.url.searchParams.get(queryParam);
    activeTab = paramValue || tabs[0]?.id;
  });

  const primaryStyles = {
    active: 'border-primary text-primary',
    inactive: 'border-transparent text-muted-foreground hover:border-muted hover:text-foreground',
  };

  const secondaryStyles = {
    active: 'bg-card text-foreground shadow-sm',
    inactive: 'text-muted-foreground hover:bg-background/70 hover:text-foreground',
  };

  const underlineStyles = {
    active: 'border-primary text-primary',
    inactive: 'border-transparent text-muted-foreground hover:text-foreground',
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

  function getCountStyles(tab: TabItem): string {
    if (tab.countVariant === 'error') {
      return 'ml-1 text-[11px] bg-destructive/10 text-destructive px-1.5 py-0.5 rounded-full';
    }
    if (tab.countVariant === 'warning') {
      return 'ml-1 text-[11px] bg-yellow-500/10 text-yellow-600 px-1.5 py-0.5 rounded-full';
    }
    if (variant === 'secondary') {
      return 'ml-1 text-[11px] bg-secondary px-1.5 py-0.5 rounded-full';
    }
    return 'ml-1 text-[11px] bg-muted px-1.5 py-0.5 rounded-full';
  }

  function isTabActive(tab: TabItem): boolean {
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

  function handleTabClick(tab: TabItem) {
    if (queryParam) {
      const nextUrl = new URL($page.url);
      nextUrl.searchParams.set(queryParam, tab.id);
      goto(`${nextUrl.pathname}${nextUrl.search}`, { replaceState });
    } else {
      activeTab = tab.id;
    }

    onTabChange?.(tab.id);
  }

  const sizeClass = $derived(
    variant === 'secondary'
      ? size === 'compact'
        ? 'px-3 py-1.5 text-sm'
        : 'px-4 py-2 text-sm'
      : size === 'compact'
        ? 'px-3 py-2 text-sm'
        : 'px-3.5 py-2.5 text-sm sm:text-[15px]'
  );
  const outerClass = $derived(
    `${sticky ? 'sticky top-0 z-20 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80' : ''} ${
      variant === 'secondary'
        ? 'rounded-lg border border-border/70 bg-muted/60 p-1'
        : variant === 'underline'
          ? 'border-b border-border/70'
          : 'border-b border-border'
    }`.trim()
  );
  const navClass = $derived(
    overflow === 'wrap'
      ? 'flex flex-wrap gap-1'
      : 'flex min-w-max gap-1 whitespace-nowrap'
  );
  const scrollClass = $derived(
    overflow === 'scroll'
      ? 'overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden'
      : ''
  );

  function renderLabel(tab: TabItem) {
    return tab.shortLabel ?? tab.label;
  }
</script>

<div class={outerClass} data-level={level}>
  <div class={scrollClass}>
    <nav class={navClass} aria-label="Tabs">
      {#each tabs as tab (tab.id)}
        {@const active = isTabActive(tab)}
        {@const tabClass = `${sizeClass} ${variant === 'secondary' ? 'rounded-md' : 'border-b-2'} inline-flex items-center gap-1.5 font-medium transition-colors ${getStyles(active)}`}
        {#if urlBased && tab.href}
          <a href={tab.href} data-sveltekit-preload-data class={tabClass} aria-current={active ? 'page' : undefined}>
            {#if tab.icon}
              <span class="shrink-0">
                {#if typeof tab.icon === 'string'}
                  {tab.icon}
                {:else}
                  <svelte:component this={tab.icon} size={16} />
                {/if}
              </span>
            {/if}
            {#if tab.shortLabel}
              <span class="sm:hidden">{renderLabel(tab)}</span>
              <span class="hidden sm:inline">{tab.label}</span>
            {:else}
              <span>{tab.label}</span>
            {/if}
            {#if tab.count !== undefined}
              <span class={getCountStyles(tab)}>{tab.count}</span>
            {/if}
          </a>
        {:else}
          <button onclick={() => handleTabClick(tab)} class={tabClass} aria-pressed={active}>
            {#if tab.icon}
              <span class="shrink-0">
                {#if typeof tab.icon === 'string'}
                  {tab.icon}
                {:else}
                  <svelte:component this={tab.icon} size={16} />
                {/if}
              </span>
            {/if}
            {#if tab.shortLabel}
              <span class="sm:hidden">{renderLabel(tab)}</span>
              <span class="hidden sm:inline">{tab.label}</span>
            {:else}
              <span>{tab.label}</span>
            {/if}
            {#if tab.count !== undefined}
              <span class={getCountStyles(tab)}>{tab.count}</span>
            {/if}
          </button>
        {/if}
      {/each}
    </nav>
  </div>
</div>
