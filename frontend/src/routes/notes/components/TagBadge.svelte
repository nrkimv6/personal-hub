<script lang="ts">
  interface Tag {
    name: string;
    color: string;
  }

  interface Props {
    tag: Tag;
    size?: 'sm' | 'md';
    removable?: boolean;
    onRemove?: () => void;
  }

  let { tag, size = 'sm', removable = false, onRemove }: Props = $props();

  const sizeClass = size === 'md'
    ? 'text-sm px-2.5 py-1'
    : 'text-xs px-2 py-0.5';
</script>

<span
  class="inline-flex items-center gap-1 rounded-full font-medium {sizeClass}"
  style="background-color: {tag.color}18; color: {tag.color}"
>
  <span
    class="rounded-full flex-shrink-0"
    class:w-1.5={size === 'sm'}
    class:h-1.5={size === 'sm'}
    class:w-2={size === 'md'}
    class:h-2={size === 'md'}
    style="background-color: {tag.color}"
  ></span>
  {tag.name}
  {#if removable}
    <button
      type="button"
      class="ml-0.5 hover:opacity-70 transition-opacity leading-none"
      onclick={onRemove}
      aria-label="태그 제거"
    >
      ×
    </button>
  {/if}
</span>
