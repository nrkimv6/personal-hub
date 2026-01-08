<script lang="ts">
  export let padding: 'none' | 'sm' | 'md' | 'lg' = 'md';
  export let shadow: boolean = true;
  export let hover: boolean = false;

  const paddings: Record<string, string> = {
    none: '',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6',
  };
</script>

<div
  class="bg-card text-card-foreground rounded-lg border border-border transition-shadow
         {shadow ? 'shadow-card' : ''}
         {hover ? 'hover:shadow-card-hover' : ''}
         {paddings[padding]}"
  {...$$restProps}
>
  <slot />
</div>
