<script lang="ts">
  export let open = false;
  export let busy = false;
  export let defaultPath = '';
  export let onclose: (() => void) | undefined = undefined;
  export let onsubmit: ((detail: { folderPath: string; recursive: boolean }) => void) | undefined = undefined;

  let folderPath = '';
  let recursive = true;

  $: if (open && !folderPath && defaultPath) {
    folderPath = defaultPath;
  }

  function closeModal() {
    if (busy) return;
    onclose?.();
  }

  function submit() {
    const normalized = folderPath.trim();
    if (!normalized || busy) return;
    onsubmit?.({ folderPath: normalized, recursive });
  }
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onclick={closeModal}>
    <div class="w-full max-w-xl rounded-xl border border-border bg-card p-4 shadow-lg" onclick={(event) => event.stopPropagation()}>
      <div class="mb-4">
        <h3 class="text-base font-semibold">폴더 스캔</h3>
        <p class="mt-1 text-sm text-muted-foreground">
          로컬 폴더를 스캔해 발표 이미지를 갤러리에 일괄 등록합니다.
        </p>
      </div>

      <label class="mb-3 block">
        <span class="mb-1 block text-xs font-medium text-muted-foreground">폴더 경로</span>
        <input
          type="text"
          bind:value={folderPath}
          placeholder="예: D:\images\slides"
          class="input input-bordered w-full"
          disabled={busy}
        />
      </label>

      <label class="mb-4 flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={recursive} disabled={busy} />
        하위 폴더 포함
      </label>

      <div class="flex justify-end gap-2">
        <button type="button" class="btn btn-outline" onclick={closeModal} disabled={busy}>취소</button>
        <button type="button" class="btn btn-primary" onclick={submit} disabled={busy || !folderPath.trim()}>
          {busy ? '스캔 중...' : '스캔 시작'}
        </button>
      </div>
    </div>
  </div>
{/if}
