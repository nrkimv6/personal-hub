<script lang="ts">
  export let variant: 'success' | 'warning' | 'error' | 'info' | 'gray' | 'purple' | 'pink' | 'primary' = 'gray';
  export let size: 'sm' | 'md' | 'lg' = 'md';
  export let dot: boolean = false;
  export let pulse: boolean = false;

  const variants: Record<string, string> = {
    success: 'bg-success-light text-success',
    warning: 'bg-warning-light text-warning-foreground',
    error: 'bg-error-light text-error',
    info: 'bg-info-light text-info',
    gray: 'bg-muted text-muted-foreground',
    purple: 'bg-purple-light text-purple',
    pink: 'bg-pink-light text-pink',
    primary: 'bg-primary-light text-primary',
  };

  const dotColors: Record<string, string> = {
    success: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-error',
    info: 'bg-info',
    gray: 'bg-muted-foreground',
    purple: 'bg-purple',
    pink: 'bg-pink',
    primary: 'bg-primary',
  };

  const sizes: Record<string, string> = {
    sm: 'text-[10px] px-1.5 py-0.5',
    md: 'text-xs px-2 py-0.5',
    lg: 'text-sm px-2.5 py-1',
  };
</script>

<span
  class="inline-flex items-center gap-1.5 rounded-md font-medium transition-colors
         {sizes[size]} {variants[variant]}"
>
  {#if dot}
    <span
      class="h-1.5 w-1.5 rounded-full {dotColors[variant]}"
      class:animate-pulse-soft={pulse}
    ></span>
  {/if}
  <slot />
</span>
