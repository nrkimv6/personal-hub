<script lang="ts">
  export let variant: 'success' | 'warning' | 'error' | 'info' | 'gray' | 'purple' | 'pink' | 'primary' = 'gray';
  export let size: 'sm' | 'md' = 'sm';

  const variants: Record<string, string> = {
    success: 'bg-success-light text-green-700',
    warning: 'bg-warning-light text-amber-700',
    error: 'bg-error-light text-red-700',
    info: 'bg-info-light text-sky-700',
    gray: 'bg-gray-100 text-gray-600',
    purple: 'bg-purple-100 text-purple-700',
    pink: 'bg-pink-100 text-pink-700',
    primary: 'bg-primary-light text-primary',
  };

  const sizes: Record<string, string> = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1 text-sm',
  };
</script>

<span class="inline-flex items-center rounded-full font-medium {sizes[size]} {variants[variant]}">
  <slot />
</span>
