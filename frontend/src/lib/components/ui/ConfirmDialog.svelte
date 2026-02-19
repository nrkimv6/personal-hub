<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  interface Props {
    open: boolean;
    title?: string;
    description?: string;
    confirmText?: string;
    destructive?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  }
  let { open = $bindable(), title = '확인', description = '', confirmText = '확인', destructive = false, onConfirm, onCancel }: Props = $props();

  function handleConfirm() {
    onConfirm();
    open = false;
  }

  function handleCancel() {
    onCancel();
    open = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && open) handleCancel();
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) handleCancel();
  }

  onMount(() => document.addEventListener('keydown', handleKeydown));
  onDestroy(() => document.removeEventListener('keydown', handleKeydown));

  $effect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
  });
</script>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center animate-fade-in"
    onclick={handleBackdropClick}
  >
    <div class="absolute inset-0 bg-foreground/50 backdrop-blur-sm"></div>
    <div class="relative bg-card text-card-foreground rounded-lg shadow-modal max-w-sm w-full mx-4 border border-border">
      <div class="p-4">
        <h3 class="text-lg font-semibold text-foreground">{title}</h3>
        {#if description}
          <p class="mt-2 text-sm text-muted-foreground">{description}</p>
        {/if}
      </div>
      <div class="p-4 border-t border-border flex justify-end gap-2">
        <button
          class="h-9 px-3 text-sm rounded-md font-medium border border-input bg-background hover:bg-accent hover:text-accent-foreground transition-colors"
          onclick={handleCancel}
        >
          취소
        </button>
        <button
          class="h-9 px-3 text-sm rounded-md font-medium text-white transition-colors
            {destructive ? 'bg-destructive hover:bg-destructive/90' : 'bg-primary hover:bg-primary-hover'}"
          onclick={handleConfirm}
        >
          {confirmText}
        </button>
      </div>
    </div>
  </div>
{/if}
