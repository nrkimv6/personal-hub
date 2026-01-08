<script lang="ts">
  export let variant: 'primary' | 'secondary' | 'destructive' | 'outline' | 'ghost' | 'link' | 'success' | 'warning' | 'info' = 'primary';
  export let size: 'xs' | 'sm' | 'md' | 'lg' | 'icon' = 'md';
  export let disabled = false;
  export let loading = false;
  export let type: 'button' | 'submit' = 'button';

  const variants: Record<string, string> = {
    primary: 'bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-active',
    secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
    destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
    outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
    ghost: 'hover:bg-accent hover:text-accent-foreground',
    link: 'text-primary underline-offset-4 hover:underline',
    success: 'bg-success text-success-foreground hover:bg-success/90',
    warning: 'bg-warning text-warning-foreground hover:bg-warning/90',
    info: 'bg-info text-info-foreground hover:bg-info/90',
  };

  const sizes: Record<string, string> = {
    xs: 'h-7 px-2 text-xs rounded-sm',
    sm: 'h-9 px-3 text-sm rounded-md',
    md: 'h-10 px-4 text-sm rounded-md',
    lg: 'h-11 px-8 text-base rounded-md',
    icon: 'h-10 w-10 rounded-md',
  };
</script>

<button
  {type}
  class="inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium
         ring-offset-background transition-colors
         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
         disabled:pointer-events-none disabled:opacity-50
         {variants[variant]} {sizes[size]}"
  disabled={disabled || loading}
  on:click
>
  {#if loading}
    <svg class="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
    </svg>
  {/if}
  <slot />
</button>
