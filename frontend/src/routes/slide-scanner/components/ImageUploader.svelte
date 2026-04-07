<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher<{ select: File }>();
  let isDragging = false;
  let fileInput: HTMLInputElement | null = null;

  function openPicker() {
    fileInput?.click();
  }

  function emitFile(file?: File) {
    if (!file) return;
    dispatch('select', file);
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    isDragging = false;
    emitFile(event.dataTransfer?.files?.[0]);
  }

  function handleInputChange(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    emitFile(target.files?.[0]);
    target.value = '';
  }
</script>

<div
  role="region"
  aria-label="파일 업로드 영역"
  class="rounded-xl border-2 border-dashed p-6 text-center transition-colors
    {isDragging ? 'border-blue-400 bg-blue-50/40' : 'border-border bg-muted/30'}"
  ondragover={(event) => {
    event.preventDefault();
    isDragging = true;
  }}
  ondragleave={() => {
    isDragging = false;
  }}
  ondrop={handleDrop}
>
  <p class="text-sm font-semibold text-foreground">이미지를 드래그하거나 파일을 선택하세요</p>
  <p class="mt-1 text-xs text-muted-foreground">JPG, PNG, WEBP</p>
  <button type="button" class="btn btn-primary mt-4" onclick={openPicker}>파일 선택</button>
  <input
    bind:this={fileInput}
    type="file"
    accept="image/*"
    class="hidden"
    onchange={handleInputChange}
  />
</div>
