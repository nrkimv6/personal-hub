<script lang="ts">
  interface Props {
    title?: string;
    subtitle?: string;
    subtitleHidden?: boolean;
    hideSubtitleOnMobile?: boolean;
    hideTitleOnMobile?: boolean;
    density?: 'default' | 'compact';
    actionsAlign?: 'start' | 'end';
    className?: string;
    navigation?: import('svelte').Snippet;
    children?: import('svelte').Snippet;
  }

  let {
    title,
    subtitle,
    subtitleHidden = false,
    hideSubtitleOnMobile = subtitleHidden,
    hideTitleOnMobile = false,
    density = 'compact',
    actionsAlign = 'end',
    className = '',
    navigation,
    children,
  }: Props = $props();

  const isCompact = $derived(density === 'compact');
  const hasNavigation = $derived(!!navigation);
  const actions = $derived(children);
  const hasActions = $derived(!!actions);
  // Compact headers may own the primary tab region. Keep title, tabs, and
  // actions in one visual band on desktop; let tabs take the horizontal
  // scroll row on mobile so actions do not overlap navigation.
  const containerClass = $derived(
    isCompact
      ? `flex min-w-0 flex-col gap-2.5 lg:min-h-10 lg:flex-row lg:items-center lg:justify-between ${className}`.trim()
      : `flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between ${className}`.trim()
  );
  const mainRowClass = $derived(
    hasNavigation
      ? 'flex min-w-0 flex-1 flex-col gap-2 lg:flex-row lg:items-center lg:gap-4'
      : 'min-w-0 flex-1'
  );
  const titleBlockClass = $derived(
    hasNavigation
      ? 'min-w-0 shrink-0 lg:max-w-[18rem] xl:max-w-[22rem]'
      : 'min-w-0'
  );
  const titleClass = $derived(
    isCompact
      ? 'text-base font-semibold leading-tight tracking-tight sm:text-lg'
      : 'text-xl font-bold tracking-tight sm:text-2xl'
  );
  const subtitleClass = $derived(
    isCompact ? 'mt-1 text-xs leading-5 text-muted-foreground sm:text-sm' : 'mt-1 text-sm text-muted-foreground'
  );
  const actionsClass = $derived(
    actionsAlign === 'start'
      ? 'flex shrink-0 flex-wrap items-center gap-2 lg:self-center lg:justify-start'
      : 'flex shrink-0 flex-wrap items-center gap-2 lg:self-center lg:justify-end'
  );
  const navigationClass = $derived(
    hasActions
      ? 'min-w-0 flex-1 lg:order-none'
      : 'min-w-0 flex-1'
  );
</script>

{#if title || subtitle || navigation || children}
  <div class={containerClass}>
    <div class={mainRowClass}>
      {#if title || subtitle}
        <div class={titleBlockClass}>
          {#if title}
            <h1 class="{titleClass} {hideTitleOnMobile ? 'hidden sm:block' : ''}">{title}</h1>
          {/if}
          {#if subtitle}
            <p class="{subtitleClass} {hideSubtitleOnMobile ? 'hidden sm:block' : ''}">{subtitle}</p>
          {/if}
        </div>
      {/if}

      {#if navigation}
        <div class={navigationClass} data-layout-slot="header-navigation">
          {@render navigation()}
        </div>
      {/if}
    </div>

    {#if hasActions}
      <div class={actionsClass}>
        {@render actions!()}
      </div>
    {/if}
  </div>
{/if}
