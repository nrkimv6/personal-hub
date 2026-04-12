<script lang="ts">
  export let enabled = true;
  export let disabled = false;
  export let canPrev = false;
  export let canNext = false;
  export let onprev: (() => void) | undefined = undefined;
  export let onnext: (() => void) | undefined = undefined;
  export let onconfirm: (() => void) | undefined = undefined;
  export let onsaveall: (() => void) | undefined = undefined;

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
      onsaveall?.();
      return;
    }

    if (event.repeat && (key === ' ' || key === 'Enter' || key === 'ArrowLeft' || key === 'ArrowRight')) {
      return;
    }

    if (key === 'ArrowLeft' && canPrev) {
      event.preventDefault();
      onprev?.();
      return;
    }

    if (key === 'ArrowRight' && canNext) {
      event.preventDefault();
      onnext?.();
      return;
    }

    if (key === ' ' || key === 'Spacebar') {
      event.preventDefault();
      if (canNext) {
        onnext?.();
      }
      return;
    }

    if (key === 'Enter') {
      event.preventDefault();
      onconfirm?.();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />
