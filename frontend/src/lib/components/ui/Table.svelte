<script lang="ts">
  export let striped: boolean = false;
  export let hoverable: boolean = true;
</script>

<div class="overflow-x-auto">
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
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background-color: var(--bg-page);
    border-bottom: 1px solid var(--border);
  }

  :global(table td) {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--gray-100);
  }

  :global(table tbody tr:hover) {
    background-color: var(--bg-page);
  }
</style>
