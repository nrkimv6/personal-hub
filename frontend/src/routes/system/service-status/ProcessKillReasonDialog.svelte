<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type { ProcessWatchItem } from '$lib/api';

  interface Props {
    open: boolean;
    item: ProcessWatchItem | null;
    defaultReason: string;
    onConfirm: (reason: string) => void | Promise<void>;
    onCancel: () => void;
  }

  let {
    open = $bindable(false),
    item,
    defaultReason = '',
    onConfirm,
    onCancel
  }: Props = $props();

  let reason = $state(defaultReason);

  $effect(() => {
    if (open) {
      reason = defaultReason;
    }
  });

  const trimmedReason = $derived(reason.trim());
  const canConfirm = $derived(trimmedReason.length >= 8);

  function handleConfirm() {
    if (!canConfirm) return;
    onConfirm(trimmedReason);
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
</script>

{#if open && item}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center animate-fade-in"
    onclick={handleBackdropClick}
  >
    <div class="absolute inset-0 bg-foreground/50 backdrop-blur-sm"></div>
    <div class="relative bg-card text-card-foreground rounded-lg shadow-modal max-w-md w-full mx-4 border border-border">
      <div class="p-4">
        <h3 class="text-lg font-semibold text-foreground">프로세스 종료 사유</h3>
        <p class="mt-2 text-sm text-muted-foreground">
          PID {item.pid} ({item.name}) 종료 사유를 입력하세요. scope={item.scope ?? 'external'}
        </p>
        <label class="block mt-4 text-xs font-medium text-muted-foreground" for="process-kill-reason">
          종료 사유
        </label>
        <textarea
          id="process-kill-reason"
          bind:value={reason}
          rows="4"
          class="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
        ></textarea>
        {#if trimmedReason.length > 0 && !canConfirm}
          <p class="mt-2 text-xs text-error">종료 사유는 최소 8자 이상이어야 합니다.</p>
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
          class="h-9 px-3 text-sm rounded-md font-medium text-white bg-destructive hover:bg-destructive/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          onclick={handleConfirm}
          disabled={!canConfirm}
        >
          계속
        </button>
      </div>
    </div>
  </div>
{/if}
