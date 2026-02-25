<script lang="ts">
  import { createEventDispatcher, onMount, onDestroy } from 'svelte';

  export let open = false;
  export let title = '';
  export let size: 'sm' | 'md' | 'lg' | 'xl' = 'md';

  const dispatch = createEventDispatcher();
  const close = () => dispatch('close');

  const sizes: Record<string, string> = {
    sm: 'max-w-sm',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
  };

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && open) close();
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) close();
  }

  onMount(() => {
    document.addEventListener('keydown', handleKeydown);
  });

  onDestroy(() => {
    document.removeEventListener('keydown', handleKeydown);
  });

  $: if (open) {
    document.body.style.overflow = 'hidden';
  } else {
    document.body.style.overflow = '';
  }
</script>

{#if open}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center animate-fade-in"
    on:click={handleBackdropClick}
    on:keydown={handleKeydown}
    role="dialog"
    aria-modal="true"
    aria-labelledby="modal-title"
    tabindex="-1"
  >
    <!-- Overlay -->
    <div class="absolute inset-0 bg-foreground/50 backdrop-blur-sm"></div>

    <!-- Modal -->
    <div class="relative bg-card text-card-foreground rounded-lg shadow-modal {sizes[size]} w-full mx-4 max-h-[95dvh] sm:max-h-[85dvh] flex flex-col border border-border">
      <!-- Header -->
      <div class="flex items-center justify-between p-4 border-b border-border">
        <h3 id="modal-title" class="text-lg font-semibold text-foreground">{title}</h3>
        <button
          on:click={close}
          class="text-muted-foreground hover:text-foreground transition-colors rounded-md p-1 hover:bg-muted"
          aria-label="Close modal"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Body -->
      <div class="flex-1 overflow-y-auto p-4">
        <slot />
      </div>

      <!-- Footer (optional) -->
      {#if $$slots.footer}
        <div class="p-4 border-t border-border flex justify-end gap-2">
          <slot name="footer" />
        </div>
      {/if}
    </div>
  </div>
{/if}
