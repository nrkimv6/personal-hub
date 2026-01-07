<script lang="ts">
  export let padding: 'none' | 'sm' | 'md' | 'lg' = 'md';
  export let shadow: boolean = true;

  const paddings: Record<string, string> = {
    none: '',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6',
  };
</script>

<div
  class="bg-card rounded-lg border border-border {shadow ? 'shadow-sm' : ''} {paddings[padding]}"
  {...$$restProps}
>
  <slot />
</div>
