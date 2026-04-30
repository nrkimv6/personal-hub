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
    children,
  }: Props = $props();

  const isCompact = $derived(density === 'compact');
  const containerClass = $derived(
    isCompact
      ? `flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between ${className}`.trim()
      : `flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between ${className}`.trim()
  );
  const titleClass = $derived(
    isCompact
      ? 'text-lg font-semibold tracking-tight sm:text-xl'
      : 'text-xl font-bold tracking-tight sm:text-2xl'
  );
  const subtitleClass = $derived(
    isCompact ? 'mt-1 text-xs text-muted-foreground sm:text-sm' : 'mt-1 text-sm text-muted-foreground'
  );
  const actionsClass = $derived(
    actionsAlign === 'start'
      ? 'flex shrink-0 flex-wrap items-center gap-2 sm:justify-start'
      : 'flex shrink-0 flex-wrap items-center gap-2 sm:justify-end'
  );
</script>

{#if title || subtitle || children}
  <div class={containerClass}>
    <div class="min-w-0 flex-1">
      {#if title}
        <h1 class="{titleClass} {hideTitleOnMobile ? 'hidden sm:block' : ''}">{title}</h1>
      {/if}
      {#if subtitle}
        <p class="{subtitleClass} {hideSubtitleOnMobile ? 'hidden sm:block' : ''}">{subtitle}</p>
      {/if}
    </div>

    {#if children}
      <div class={actionsClass}>
        {@render children()}
      </div>
    {/if}
  </div>
{/if}
