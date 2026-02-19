<script lang="ts">
  interface Props {
    variant?: 'success' | 'warning' | 'error' | 'gray';
    size?: 'sm' | 'md';
    pulse?: boolean;
  }
  let { variant = 'gray', size = 'sm', pulse = false }: Props = $props();

  const colors: Record<string, string> = {
    success: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-error',
    gray: 'bg-muted-foreground',
  };

  const sizes: Record<string, string> = {
    sm: 'h-2 w-2',
    md: 'h-2.5 w-2.5',
  };
</script>

<span
  class="inline-block rounded-full shrink-0 {sizes[size]} {colors[variant]}"
  class:animate-pulse-soft={pulse}
></span>
