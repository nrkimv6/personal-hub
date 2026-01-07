<script lang="ts">
  export let variant: 'primary' | 'secondary' | 'danger' | 'warning' | 'success' | 'ghost' | 'info' = 'primary';
  export let size: 'xs' | 'sm' | 'md' | 'lg' = 'md';
  export let disabled = false;
  export let loading = false;
  export let type: 'button' | 'submit' = 'button';

  const variants: Record<string, string> = {
    primary: 'bg-primary hover:bg-primary-hover text-white',
    secondary: 'bg-white border border-gray-300 hover:bg-gray-50 text-gray-700',
    danger: 'bg-error hover:bg-red-600 text-white',
    warning: 'bg-warning hover:bg-amber-600 text-white',
    success: 'bg-success hover:bg-green-600 text-white',
    ghost: 'bg-transparent hover:bg-gray-100 text-primary',
    info: 'bg-info-light hover:bg-sky-200 text-sky-700',
  };

  const sizes: Record<string, string> = {
    xs: 'h-6 px-2 text-xs',
    sm: 'h-8 px-3 text-sm',
    md: 'h-10 px-4 text-sm',
    lg: 'h-12 px-6 text-base',
  };
</script>

<button
  {type}
  class="inline-flex items-center justify-center rounded-md font-medium transition-colors
         disabled:opacity-50 disabled:cursor-not-allowed
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
