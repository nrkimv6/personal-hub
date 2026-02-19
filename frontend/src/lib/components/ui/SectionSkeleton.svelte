<script lang="ts">
  interface Props {
    rows?: number;
  }
  let { rows = 3 }: Props = $props();
</script>

<div class="bg-card text-card-foreground rounded-lg border border-border shadow-card p-4 space-y-2">
  {#each Array(rows) as _}
    <div class="h-12 rounded-md animate-skeleton-shimmer"></div>
  {/each}
</div>
