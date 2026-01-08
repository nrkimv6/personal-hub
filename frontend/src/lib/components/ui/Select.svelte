<script lang="ts">
  export let value: string = '';
  export let options: Array<{ value: string; label: string }> = [];
  export let placeholder: string = '선택하세요';
  export let disabled: boolean = false;
  export let size: 'sm' | 'md' | 'lg' = 'md';

  const sizes: Record<string, string> = {
    sm: 'h-8 px-2 text-sm',
    md: 'h-10 px-3 text-sm',
    lg: 'h-12 px-4 text-base',
  };
</script>

<select
  bind:value
  {disabled}
  class="w-full rounded-md border border-input bg-background text-foreground transition-colors outline-none
         ring-offset-background cursor-pointer
         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2
         disabled:bg-muted disabled:cursor-not-allowed disabled:opacity-50
         {sizes[size]}"
  on:change
  {...$$restProps}
>
  {#if placeholder}
    <option value="" disabled class="text-muted-foreground">{placeholder}</option>
  {/if}
  {#each options as opt}
    <option value={opt.value}>{opt.label}</option>
  {/each}
</select>
