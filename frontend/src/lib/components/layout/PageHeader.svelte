<script lang="ts">
  interface Props {
    title: string;
    subtitle?: string;
    subtitleHidden?: boolean; // true이면 모바일에서 subtitle 숨김 (hidden sm:block)
    children?: import('svelte').Snippet;
  }

  let { title, subtitle, subtitleHidden = false, children }: Props = $props();
</script>

<div class="flex items-start justify-between mb-4">
  <div>
    <h1 class="text-xl font-bold tracking-tight sm:text-2xl">{title}</h1>
    {#if subtitle}
      {#if subtitleHidden}
        <p class="mt-1 text-sm text-muted-foreground hidden sm:block">{subtitle}</p>
      {:else}
        <p class="mt-1 text-sm text-muted-foreground">{subtitle}</p>
      {/if}
    {/if}
  </div>
  {#if children}
    <div class="flex items-center gap-2 shrink-0">
      {@render children()}
    </div>
  {/if}
</div>
