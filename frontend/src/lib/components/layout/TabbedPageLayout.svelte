<script lang="ts">
  import PageHeader from './PageHeader.svelte';
  import TabNav from './TabNav.svelte';

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
    children?: import('svelte').Snippet<[]>;
    title: string;
    subtitle?: string;
    tabs?: Tab[];
    activeTab?: string;
    queryParam?: string;
    replaceState?: boolean;
    size?: 'default' | 'compact';
    variant?: 'primary' | 'secondary' | 'underline';
    containerClass?: string;
    contentClass?: string;
  }

  let {
    title,
    subtitle,
    tabs = [],
    activeTab = $bindable(),
    queryParam = 'tab',
    replaceState = true,
    size = 'default',
    variant = 'primary',
    containerClass = 'p-4 lg:p-6 space-y-4',
    contentClass,
  }: Props = $props();
</script>

<div class={containerClass}>
  <PageHeader {title} {subtitle} />

  {#if tabs.length > 0}
    <TabNav
      {tabs}
      bind:activeTab
      {variant}
      {queryParam}
      {replaceState}
      {size}
    />
  {/if}

  <div class={contentClass}>
    {@render children?.()}
  </div>
</div>
