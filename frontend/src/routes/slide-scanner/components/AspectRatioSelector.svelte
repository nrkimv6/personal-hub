<script lang="ts">
  import type { AspectRatioValue } from '$lib/api/slide-scanner';

  export let value: AspectRatioValue = 'AUTO';
  export let disabled = false;
  export let onchange: ((detail: { value: AspectRatioValue }) => void) | undefined = undefined;

  const options: Array<{ label: string; value: AspectRatioValue }> = [
    { label: 'Auto', value: 'AUTO' },
    { label: '16:9', value: '16:9' },
    { label: '4:3', value: '4:3' }
  ];

  function select(next: AspectRatioValue) {
    if (disabled) return;
    onchange?.({ value: next });
  }
</script>

<div class="flex items-center gap-2">
  <span class="text-xs font-medium text-muted-foreground">비율</span>
  <div class="inline-flex rounded-md border border-border bg-background p-1">
    {#each options as option}
      <button
        type="button"
        class="btn btn-xs {value === option.value ? 'btn-primary' : 'btn-ghost'}"
        onclick={() => select(option.value)}
        disabled={disabled}
      >
        {option.label}
      </button>
    {/each}
  </div>
</div>
