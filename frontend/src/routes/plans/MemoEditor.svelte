<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { planRecordsApi, type PlanRecord } from '$lib/api/plan-records';

  export let filePath: string;
  export let onSaved: ((record: PlanRecord) => void) | undefined = undefined;

  let record: PlanRecord | null = null;
  let draftText = '';
  let saveStatus: 'idle' | 'saving' | 'saved' | 'draft' | 'error' = 'idle';
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let error = '';

  async function loadRecord() {
    try {
      record = await planRecordsApi.byPath(filePath);
      draftText = record.memo_draft ?? record.memo ?? '';
      saveStatus = record.memo_draft ? 'draft' : 'idle';
    } catch (e) {
      error = e instanceof Error ? e.message : '레코드 로드 실패';
    }
  }

  function handleInput() {
    saveStatus = 'saving';
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      if (!record) return;
      try {
        record = await planRecordsApi.updateMemo(record.id, 'draft', draftText);
        saveStatus = 'draft';
      } catch (e) {
        saveStatus = 'error';
      }
    }, 300);
  }

  async function confirmMemo() {
    if (!record) return;
    try {
      saveStatus = 'saving';
      record = await planRecordsApi.updateMemo(record.id, 'confirm');
      draftText = record.memo ?? '';
      saveStatus = 'saved';
      onSaved?.(record);
      setTimeout(() => { saveStatus = 'idle'; }, 2000);
    } catch (e) {
      saveStatus = 'error';
    }
  }

  async function rollbackMemo() {
    if (!record) return;
    try {
      record = await planRecordsApi.updateMemo(record.id, 'rollback');
      draftText = record.memo_draft ?? record.memo ?? '';
      saveStatus = 'idle';
    } catch (e) {
      saveStatus = 'error';
    }
  }

  onMount(loadRecord);

  onDestroy(() => {
    if (debounceTimer) clearTimeout(debounceTimer);
  });

  const statusLabel: Record<string, string> = {
    idle: '',
    saving: '저장 중...',
    saved: '저장됨',
    draft: '초안',
    error: '오류',
  };

  const statusClass: Record<string, string> = {
    idle: 'text-muted-foreground',
    saving: 'text-yellow-500',
    saved: 'text-green-600',
    draft: 'text-primary',
    error: 'text-red-500',
  };
</script>

{#if error}
  <p class="text-sm text-red-500">{error}</p>
{:else if !record}
  <p class="text-sm text-muted-foreground">로드 중...</p>
{:else}
  <div class="flex flex-col gap-2 h-full">
    <div class="flex items-center justify-between text-xs">
      <span class={statusClass[saveStatus]}>{statusLabel[saveStatus]}</span>
      <div class="flex gap-2">
        <button
          class="px-2 py-1 rounded text-xs bg-muted hover:bg-secondary text-muted-foreground"
          on:click={rollbackMemo}
        >롤백</button>
        <button
          class="px-2 py-1 rounded text-xs bg-primary hover:bg-primary-hover text-primary-foreground"
          on:click={confirmMemo}
        >저장</button>
      </div>
    </div>
    <textarea
      class="flex-1 w-full p-2 rounded bg-background text-foreground text-sm border border-border resize-none focus:outline-none focus:border-primary"
      placeholder="메모를 입력하세요..."
      bind:value={draftText}
      on:input={handleInput}
      rows={8}
    ></textarea>
  </div>
{/if}
