<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher<{
    prev: void;
    next: void;
    confirm: void;
    saveAll: void;
  }>();

  export let enabled = true;
  export let disabled = false;
  export let canPrev = false;
  export let canNext = false;

  function isEditableTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    const tagName = target.tagName.toLowerCase();
    if (tagName === 'input' || tagName === 'textarea' || tagName === 'select') return true;
    return target.isContentEditable;
  }

  function handleKeydown(event: KeyboardEvent) {
    if (!enabled || disabled) return;
    if (isEditableTarget(event.target)) return;

    const key = event.key;
    const ctrlOrMeta = event.ctrlKey || event.metaKey;

    if (ctrlOrMeta && key.toLowerCase() === 's') {
      event.preventDefault();
      dispatch('saveAll');
      return;
    }

    if (event.repeat && (key === ' ' || key === 'Enter' || key === 'ArrowLeft' || key === 'ArrowRight')) {
      return;
    }

    if (key === 'ArrowLeft' && canPrev) {
      event.preventDefault();
      dispatch('prev');
      return;
    }

    if (key === 'ArrowRight' && canNext) {
      event.preventDefault();
      dispatch('next');
      return;
    }

    if (key === ' ' || key === 'Spacebar') {
      event.preventDefault();
      if (canNext) {
        dispatch('next');
      }
      return;
    }

    if (key === 'Enter') {
      event.preventDefault();
      dispatch('confirm');
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />
