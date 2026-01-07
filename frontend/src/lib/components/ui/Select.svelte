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
  class="w-full rounded-md border border-border transition-colors outline-none
         focus:border-primary focus:ring-2 focus:ring-primary/20
         disabled:bg-gray-50 disabled:cursor-not-allowed
         cursor-pointer bg-white
         {sizes[size]}"
  on:change
  {...$$restProps}
>
  {#if placeholder}
    <option value="" disabled>{placeholder}</option>
  {/if}
  {#each options as opt}
    <option value={opt.value}>{opt.label}</option>
  {/each}
</select>
