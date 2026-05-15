<script lang="ts">
  import PageHeader from './PageHeader.svelte';
  import TabNav, { type TabItem } from './TabNav.svelte';

  interface Props {
    children?: import('svelte').Snippet<[]>;
    actions?: import('svelte').Snippet<[]>;
    toolbar?: import('svelte').Snippet<[]>;
    title?: string;
    subtitle?: string;
    primaryTabs?: TabItem[];
    secondaryTabs?: TabItem[];
    activePrimaryTab?: string;
    activeSecondaryTab?: string;
    primaryQueryParam?: string;
    secondaryQueryParam?: string;
    primaryUrlBased?: boolean;
    secondaryUrlBased?: boolean;
    primaryReplaceState?: boolean;
    secondaryReplaceState?: boolean;
    primaryTabsPlacement?: 'header' | 'below';
    density?: 'default' | 'compact';
    hideTitleOnMobile?: boolean;
    hideSubtitleOnMobile?: boolean;
    stickyTabs?: boolean;
    containerClass?: string;
    contentClass?: string;
  }

  let {
    title,
    subtitle,
    primaryTabs = [],
    secondaryTabs = [],
    activePrimaryTab = $bindable(),
    activeSecondaryTab = $bindable(),
    children,
    actions,
    toolbar,
    primaryQueryParam = 'tab',
    secondaryQueryParam = 'subtab',
    primaryUrlBased = false,
    secondaryUrlBased = false,
    primaryReplaceState = true,
    secondaryReplaceState = true,
    primaryTabsPlacement = 'header',
    density = 'compact',
    hideTitleOnMobile = false,
    hideSubtitleOnMobile = false,
    stickyTabs = false,
    containerClass,
    contentClass = '',
  }: Props = $props();

  // Slot order is intentionally fixed for every tabbed surface. Primary tabs
  // default to PageHeader's navigation region; toolbar and secondary tabs stay
  // below the header so filters do not compete with section navigation.
  const resolvedContainerClass = $derived(
    containerClass ?? (density === 'compact' ? 'space-y-3 p-4 lg:p-6' : 'space-y-4 p-4 lg:p-6')
  );
  const contentWrapperClass = $derived(contentClass || 'min-w-0');
  const primaryTabsInHeader = $derived(primaryTabsPlacement === 'header' && primaryTabs.length > 0);
  const hasHeader = $derived(!!title || !!subtitle || !!actions || primaryTabsInHeader);
  const resolvedPrimaryQueryParam = $derived(primaryUrlBased ? undefined : primaryQueryParam);
  const resolvedSecondaryQueryParam = $derived(secondaryUrlBased ? undefined : secondaryQueryParam);
</script>

{#snippet primaryTabsNavigation()}
  <TabNav
    tabs={primaryTabs}
    bind:activeTab={activePrimaryTab}
    variant="primary"
    level="primary"
    queryParam={resolvedPrimaryQueryParam}
    urlBased={primaryUrlBased}
    replaceState={primaryReplaceState}
    size="header"
    sticky={false}
    overflow="scroll"
  />
{/snippet}

<div class={resolvedContainerClass}>
  {#if hasHeader}
    <div data-layout-slot="header">
      <PageHeader
        {title}
        {subtitle}
        density={density}
        {hideTitleOnMobile}
        {hideSubtitleOnMobile}
        navigation={primaryTabsInHeader ? primaryTabsNavigation : undefined}
      >
        {#if actions}
          {@render actions()}
        {/if}
      </PageHeader>
    </div>
  {/if}

  {#if primaryTabs.length > 0 && primaryTabsPlacement === 'below'}
    <div data-layout-slot="primary-tabs">
      <TabNav
        tabs={primaryTabs}
        bind:activeTab={activePrimaryTab}
        variant="primary"
        level="primary"
        queryParam={resolvedPrimaryQueryParam}
        urlBased={primaryUrlBased}
        replaceState={primaryReplaceState}
        size={density === 'compact' ? 'compact' : 'default'}
        sticky={stickyTabs}
        overflow="scroll"
      />
    </div>
  {/if}

  {#if toolbar}
    <div class="flex min-w-0 flex-col gap-3" data-layout-slot="toolbar">
      {@render toolbar()}
    </div>
  {/if}

  {#if secondaryTabs.length > 0}
    <div data-layout-slot="secondary-tabs">
      <TabNav
        tabs={secondaryTabs}
        bind:activeTab={activeSecondaryTab}
        variant="secondary"
        level="secondary"
        queryParam={resolvedSecondaryQueryParam}
        urlBased={secondaryUrlBased}
        replaceState={secondaryReplaceState}
        size="compact"
        sticky={stickyTabs}
        overflow="scroll"
      />
    </div>
  {/if}

  <div class={contentWrapperClass} data-layout-slot="content">
    {@render children?.()}
  </div>
</div>
