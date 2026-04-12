<script lang="ts">
  export interface PdfExportItem {
    id: number;
    file_name: string;
    captured_at?: string | null;
  }

  export let open = false;
  export let busy = false;
  export let selectedSlides: PdfExportItem[] = [];
  export let onclose: (() => void) | undefined = undefined;
  export let onsubmit: ((detail: { filename: string }) => void) | undefined = undefined;

  let filename = '';
  let initialized = false;

  function defaultFilename(): string {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    return `slides_${y}${m}${d}`;
  }

  $: if (open && !initialized) {
    filename = defaultFilename();
    initialized = true;
  }

  $: if (!open) {
    initialized = false;
  }

  function closeModal() {
    if (busy) return;
    onclose?.();
  }

  function submit() {
    const normalized = filename.trim();
    if (!normalized || busy || selectedSlides.length === 0) return;
    onsubmit?.({ filename: normalized });
  }

  function formatCapturedAt(value: string | null | undefined): string {
    if (!value) return '-';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString();
  }
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onclick={closeModal}>
    <div
      class="w-full max-w-2xl rounded-xl border border-border bg-card p-4 shadow-lg"
      onclick={(event) => event.stopPropagation()}
    >
      <div class="mb-4">
        <h3 class="text-base font-semibold">PDF 내보내기</h3>
        <p class="mt-1 text-sm text-muted-foreground">
          선택한 보정 결과 이미지를 PDF 한 파일로 묶어 다운로드합니다.
        </p>
      </div>

      <label class="mb-3 block">
        <span class="mb-1 block text-xs font-medium text-muted-foreground">파일명</span>
        <input
          type="text"
          bind:value={filename}
          placeholder="예: 발표자료_정리본"
          class="input input-bordered w-full"
          disabled={busy}
        />
      </label>

      <div class="mb-4 rounded-lg border border-border bg-muted/30 p-3">
        <p class="mb-2 text-xs font-medium text-muted-foreground">내보낼 순서 ({selectedSlides.length}건)</p>
        <div class="max-h-48 space-y-1 overflow-auto text-xs">
          {#each selectedSlides as slide, index}
            <div class="flex items-center justify-between rounded bg-card px-2 py-1">
              <span class="truncate">{index + 1}. {slide.file_name}</span>
              <span class="ml-2 shrink-0 text-muted-foreground">{formatCapturedAt(slide.captured_at)}</span>
            </div>
          {/each}
        </div>
      </div>

      <div class="flex justify-end gap-2">
        <button type="button" class="btn btn-outline" onclick={closeModal} disabled={busy}>취소</button>
        <button
          type="button"
          class="btn btn-primary"
          onclick={submit}
          disabled={busy || !filename.trim() || selectedSlides.length === 0}
        >
          {busy ? '내보내는 중...' : 'PDF 다운로드'}
        </button>
      </div>
    </div>
  </div>
{/if}
