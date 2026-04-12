<script lang="ts">
  export let currentPage: number = 1;
  export let totalPages: number = 1;
  export let siblingsCount: number = 1;
  export let onchange: ((page: number) => void) | undefined = undefined;

  function goToPage(page: number) {
    if (page >= 1 && page <= totalPages && page !== currentPage) {
      onchange?.(page);
    }
  }

  $: pages = generatePages(currentPage, totalPages, siblingsCount);

  function generatePages(current: number, total: number, siblings: number): (number | '...')[] {
    const result: (number | '...')[] = [];

    if (total <= 7) {
      for (let i = 1; i <= total; i++) result.push(i);
      return result;
    }

    result.push(1);

    const start = Math.max(2, current - siblings);
    const end = Math.min(total - 1, current + siblings);

    if (start > 2) result.push('...');
    for (let i = start; i <= end; i++) result.push(i);
    if (end < total - 1) result.push('...');

    result.push(total);
    return result;
  }
</script>

<nav class="flex items-center gap-1" aria-label="Pagination">
  <button
    class="px-3 py-1.5 text-sm rounded-md border border-border bg-background hover:bg-muted text-foreground
           disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    disabled={currentPage === 1}
    onclick={() => goToPage(currentPage - 1)}
  >
    이전
  </button>

  {#each pages as page}
    {#if page === '...'}
      <span class="px-2 text-muted-foreground">...</span>
    {:else}
      <button
        class="px-3 py-1.5 text-sm rounded-md transition-colors
               {currentPage === page
                 ? 'bg-primary text-primary-foreground'
                 : 'hover:bg-muted text-foreground'}"
        onclick={() => goToPage(page)}
      >
        {page}
      </button>
    {/if}
  {/each}

  <button
    class="px-3 py-1.5 text-sm rounded-md border border-border bg-background hover:bg-muted text-foreground
           disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    disabled={currentPage === totalPages}
    onclick={() => goToPage(currentPage + 1)}
  >
    다음
  </button>
</nav>
