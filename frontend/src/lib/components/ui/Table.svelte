<script lang="ts">
  export let striped: boolean = false;
  export let hoverable: boolean = true;
</script>

<div class="overflow-x-auto rounded-md border border-border">
  <table class="w-full border-collapse">
    <slot />
  </table>
</div>

<style>
  :global(table th) {
    padding: 0.75rem 1rem;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 500;
    color: hsl(var(--muted-foreground));
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background-color: hsl(var(--muted));
    border-bottom: 1px solid hsl(var(--border));
  }

  :global(table td) {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid hsl(var(--border));
  }

  :global(table tbody tr:hover) {
    background-color: hsl(var(--muted));
  }

  :global(table tbody tr:last-child td) {
    border-bottom: none;
  }
</style>
