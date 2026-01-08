<script lang="ts">
  export let value: number = 0;
  export let max: number = 100;
  export let size: 'sm' | 'md' | 'lg' = 'md';
  export let showLabel: boolean = true;
  export let variant: 'primary' | 'success' | 'warning' | 'error' | 'info' = 'primary';

  $: percentage = Math.min(100, Math.max(0, (value / max) * 100));

  const sizes: Record<string, { width: string; height: string; text: string }> = {
    sm: { width: 'w-24', height: 'h-1.5', text: 'text-xs' },
    md: { width: 'w-32', height: 'h-2', text: 'text-sm' },
    lg: { width: 'w-48', height: 'h-3', text: 'text-base' },
  };

  const variants: Record<string, string> = {
    primary: 'bg-primary',
    success: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-error',
    info: 'bg-info',
  };
</script>

<div class="flex items-center gap-2">
  <div class="{sizes[size].width} {sizes[size].height} bg-muted rounded-full overflow-hidden">
    <div
      class="{sizes[size].height} {variants[variant]} rounded-full transition-all duration-300"
      style="width: {percentage}%"
    />
  </div>
  {#if showLabel}
    <span class="{sizes[size].text} text-muted-foreground font-medium">
      {value}/{max}
    </span>
  {/if}
</div>
