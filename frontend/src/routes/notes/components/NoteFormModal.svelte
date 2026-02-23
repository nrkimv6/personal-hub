<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { Note, TagDef } from '$lib/api/notes';
  import { X, Loader2 } from 'lucide-svelte';
  import TagInput from './TagInput.svelte';

  interface Props {
    mode: 'create' | 'edit';
    note?: Note;
    onSave: () => void;
    onClose: () => void;
  }

  let { mode, note, onSave, onClose }: Props = $props();

  let title = $state(note?.title ?? '');
  let content = $state(note?.content ?? '');
  let remark = $state(note?.remark ?? '');
  let tagIds = $state<number[]>(note?.tags.map((t) => t.id) ?? []);
  let allTags = $state<TagDef[]>([]);
  let saving = $state(false);
  let error = $state('');

  async function loadTags() {
    allTags = await notesApi.listTags().catch(() => []);
  }

  async function refreshTags() {
    allTags = await notesApi.listTags().catch(() => []);
  }

  async function handleSave() {
    if (!title.trim()) { error = '제목을 입력해주세요.'; return; }
    saving = true;
    error = '';
    try {
      if (mode === 'create') {
        await notesApi.create({ title: title.trim(), content, remark: remark || undefined, tag_ids: tagIds });
      } else if (note) {
        await notesApi.update(note.id, { title: title.trim(), content, remark: remark || undefined, tag_ids: tagIds });
      }
      onSave();
    } catch (e: any) {
      error = e.message;
    } finally {
      saving = false;
    }
  }

  onMount(loadTags);
</script>

<div
  class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-foreground/20 backdrop-blur-sm animate-fade-in"
  onclick={onClose}
>
  <div
    class="relative w-full max-w-2xl max-h-[90vh] bg-card rounded-xl shadow-modal flex flex-col overflow-hidden"
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
  >
    <!-- 헤더 -->
    <div class="flex items-center justify-between p-5 border-b border-border">
      <h2 class="text-base font-semibold text-foreground">
        {mode === 'create' ? '새 메모' : '메모 수정'}
      </h2>
      <button
        onclick={onClose}
        class="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
      ><X class="w-4 h-4" /></button>
    </div>

    <!-- 폼 -->
    <div class="flex flex-col gap-4 p-5 overflow-y-auto">
      <!-- 제목 -->
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="block text-xs font-medium text-muted-foreground">제목 *</label>
          <span class="text-xs text-muted-foreground">{title.length}/200</span>
        </div>
        <input
          type="text"
          bind:value={title}
          placeholder="메모 제목..."
          maxlength="200"
          class="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
            focus:outline-none focus:ring-2 focus:ring-ring/30"
        />
      </div>

      <!-- 본문 -->
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1">내용 (마크다운 지원)</label>
        <textarea
          bind:value={content}
          placeholder="마크다운 또는 코드블록 입력..."
          class="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
            focus:outline-none focus:ring-2 focus:ring-ring/30 font-mono resize-y"
          style="min-height: 240px"
        ></textarea>
      </div>

      <!-- 비고 -->
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1">비고</label>
        <input
          type="text"
          bind:value={remark}
          placeholder="URL, source, or reference…"
          class="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
            focus:outline-none focus:ring-2 focus:ring-ring/30"
        />
      </div>

      <!-- 태그 -->
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1">태그</label>
        <TagInput
          selectedTagIds={tagIds}
          {allTags}
          onChange={(ids) => (tagIds = ids)}
          onTagsRefresh={refreshTags}
        />
      </div>

      {#if error}
        <p class="text-sm text-destructive">{error}</p>
      {/if}
    </div>

    <!-- 하단 -->
    <div class="flex justify-end gap-2 p-4 border-t border-border">
      <button
        onclick={onClose}
        class="px-4 py-2 text-sm rounded-lg bg-muted text-foreground hover:bg-muted/80 transition-colors"
      >취소</button>
      <button
        onclick={handleSave}
        disabled={saving}
        class="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary-hover disabled:opacity-50 transition-colors"
      >
        {#if saving}
          <Loader2 class="w-4 h-4 animate-spin" />
          저장 중...
        {:else}
          저장
        {/if}
      </button>
    </div>
  </div>
</div>
