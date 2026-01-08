<script lang="ts">
  export let value: string = '';
  export let type: 'text' | 'email' | 'password' | 'number' | 'url' | 'search' = 'text';
  export let placeholder: string = '';
  export let disabled: boolean = false;
  export let error: boolean = false;
  export let size: 'sm' | 'md' | 'lg' = 'md';

  const sizes: Record<string, string> = {
    sm: 'h-8 px-2 text-sm',
    md: 'h-10 px-3 text-sm',
    lg: 'h-12 px-4 text-base',
  };
</script>

<input
  {type}
  bind:value
  {placeholder}
  {disabled}
  class="w-full rounded-md border bg-background text-foreground transition-colors outline-none
         ring-offset-background
         placeholder:text-muted-foreground
         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
         disabled:bg-muted disabled:cursor-not-allowed disabled:opacity-50
         {error ? 'border-error focus-visible:ring-error' : 'border-input'}
         {sizes[size]}"
  on:input
  on:change
  on:focus
  on:blur
  {...$$restProps}
/>
