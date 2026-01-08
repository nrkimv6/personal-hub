<script lang="ts">
  export let variant: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' | 'error' | 'info' | 'gray' | 'purple' | 'pink' | 'primary' = 'default';
  export let size: 'sm' | 'md' | 'lg' = 'sm';

  const variants: Record<string, string> = {
    default: 'border-transparent bg-primary text-primary-foreground hover:bg-primary/80',
    secondary: 'border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
    destructive: 'border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80',
    outline: 'border-border text-foreground',
    success: 'border-transparent bg-success-light text-success',
    warning: 'border-transparent bg-warning-light text-warning-foreground',
    error: 'border-transparent bg-error-light text-error',
    info: 'border-transparent bg-info-light text-info',
    gray: 'border-transparent bg-muted text-muted-foreground',
    purple: 'border-transparent bg-purple-light text-purple',
    pink: 'border-transparent bg-pink-light text-pink',
    primary: 'border-transparent bg-primary-light text-primary',
  };

  const sizes: Record<string, string> = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-0.5 text-xs',
    lg: 'px-3 py-1 text-sm',
  };
</script>

<span
  class="inline-flex items-center rounded-full border font-semibold transition-colors
         focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2
         {sizes[size]} {variants[variant]}"
>
  <slot />
</span>
