<script lang="ts">
  export let value: number = 0;
  export let max: number = 100;
  export let size: 'sm' | 'md' | 'lg' = 'md';
  export let showValue: boolean = true;
  export let label: string = '';
  export let thresholds: { warning: number; error: number } = { warning: 70, error: 90 };

  $: percentage = Math.min(Math.max((value / max) * 100, 0), 100);

  $: colorClass = percentage >= thresholds.error
    ? 'text-error'
    : percentage >= thresholds.warning
    ? 'text-warning'
    : 'text-success';

  $: strokeClass = percentage >= thresholds.error
    ? 'stroke-error'
    : percentage >= thresholds.warning
    ? 'stroke-warning'
    : 'stroke-success';

  const sizes = {
    sm: { size: 48, stroke: 4, text: 'text-xs' },
    md: { size: 64, stroke: 5, text: 'text-sm' },
    lg: { size: 80, stroke: 6, text: 'text-base' },
  };

  $: config = sizes[size];
  $: radius = (config.size - config.stroke) / 2;
  $: circumference = 2 * Math.PI * radius;
  $: offset = circumference - (percentage / 100) * circumference;
</script>

<div class="flex flex-col items-center gap-1">
  <div class="relative">
    <svg
      width={config.size}
      height={config.size}
      class="rotate-[-90deg]"
    >
      <!-- Background circle -->
      <circle
        cx={config.size / 2}
        cy={config.size / 2}
        r={radius}
        fill="none"
        stroke-width={config.stroke}
        class="stroke-muted"
      />
      <!-- Progress circle -->
      <circle
        cx={config.size / 2}
        cy={config.size / 2}
        r={radius}
        fill="none"
        stroke-width={config.stroke}
        stroke-linecap="round"
        stroke-dasharray={circumference}
        stroke-dashoffset={offset}
        class="transition-all duration-500 {strokeClass}"
      />
    </svg>
    {#if showValue}
      <div class="absolute inset-0 flex items-center justify-center">
        <span class="font-semibold {config.text} {colorClass}">
          {Math.round(percentage)}%
        </span>
      </div>
    {/if}
  </div>
  {#if label}
    <span class="text-xs text-muted-foreground">{label}</span>
  {/if}
</div>
