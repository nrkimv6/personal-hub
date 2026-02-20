<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { Note, TagDef } from '$lib/api/notes';
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

<div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onclick={onClose}>
  <div
    class="relative w-full max-w-xl bg-white dark:bg-gray-800 rounded-2xl shadow-xl flex flex-col overflow-hidden"
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
  >
    <!-- 헤더 -->
    <div class="flex items-center justify-between p-5 border-b border-gray-200 dark:border-gray-700">
      <h2 class="text-lg font-semibold text-gray-900 dark:text-white">
        {mode === 'create' ? '새 메모' : '메모 수정'}
      </h2>
      <button onclick={onClose} class="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
    </div>

    <!-- 폼 -->
    <div class="flex flex-col gap-4 p-5 overflow-y-auto max-h-[70vh]">
      <!-- 제목 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">제목 *</label>
        <input
          type="text"
          bind:value={title}
          placeholder="메모 제목..."
          class="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <!-- 본문 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">내용 (마크다운 지원)</label>
        <textarea
          bind:value={content}
          rows="10"
          placeholder="마크다운 또는 코드블록 입력..."
          class="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono resize-y"
        ></textarea>
      </div>

      <!-- 비고 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">비고</label>
        <input
          type="text"
          bind:value={remark}
          placeholder="참고 URL, 출처 등..."
          class="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <!-- 태그 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">태그</label>
        <TagInput
          selectedTagIds={tagIds}
          {allTags}
          onChange={(ids) => (tagIds = ids)}
          onTagsRefresh={refreshTags}
        />
      </div>

      {#if error}
        <p class="text-sm text-red-500">{error}</p>
      {/if}
    </div>

    <!-- 하단 -->
    <div class="flex justify-end gap-2 p-4 border-t border-gray-200 dark:border-gray-700">
      <button onclick={onClose} class="px-4 py-2 text-sm rounded-lg border hover:bg-gray-50 dark:hover:bg-gray-700">취소</button>
      <button
        onclick={handleSave}
        disabled={saving}
        class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
      >{saving ? '저장 중...' : '저장'}</button>
    </div>
  </div>
</div>
