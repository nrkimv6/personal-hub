<script lang="ts">
  export let checked: boolean = false;
  export let disabled: boolean = false;
  export let size: 'sm' | 'md' = 'md';

  const sizes: Record<string, { track: string; thumb: string; translate: string }> = {
    sm: { track: 'w-8 h-4', thumb: 'w-3 h-3', translate: 'translate-x-4' },
    md: { track: 'w-11 h-6', thumb: 'w-5 h-5', translate: 'translate-x-5' },
  };
</script>

<button
  type="button"
  role="switch"
  aria-checked={checked}
  aria-label="toggle"
  {disabled}
  class="relative inline-flex shrink-0 cursor-pointer rounded-full transition-colors
         ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
         disabled:opacity-50 disabled:cursor-not-allowed
         {checked ? 'bg-primary' : 'bg-muted'}
         {sizes[size].track}"
  on:click={() => !disabled && (checked = !checked)}
>
  <span
    class="pointer-events-none inline-block rounded-full bg-background shadow-sm transform transition-transform
           {checked ? sizes[size].translate : 'translate-x-0.5'}
           {sizes[size].thumb}"
    style="margin-top: 0.125rem;"
  ></span>
</button>
