<script lang="ts">
  import type { Note } from '$lib/api/notes';
  import { notesApi } from '$lib/api/notes';

  interface Props {
    note: Note;
    onOpen: (note: Note) => void;
    onEdit: (note: Note) => void;
    onRefresh: () => void;
  }

  let { note, onOpen, onEdit, onRefresh }: Props = $props();

  let archiving = $state(false);
  let deleting = $state(false);
  let pinning = $state(false);

  async function handlePin(e: Event) {
    e.stopPropagation();
    pinning = true;
    try {
      await notesApi.togglePin(note.id);
      onRefresh();
    } finally {
      pinning = false;
    }
  }

  async function handleArchive(e: Event) {
    e.stopPropagation();
    if (!confirm('이 메모를 아카이브로 이동하시겠습니까?')) return;
    archiving = true;
    try {
      await notesApi.archive(note.id);
      onRefresh();
    } catch (err: any) {
      alert(err.message);
    } finally {
      archiving = false;
    }
  }

  async function handleDelete(e: Event) {
    e.stopPropagation();
    if (!confirm('이 메모를 삭제하시겠습니까?')) return;
    deleting = true;
    try {
      await notesApi.remove(note.id);
      onRefresh();
    } finally {
      deleting = false;
    }
  }

  function handleCopy(e: Event) {
    e.stopPropagation();
    navigator.clipboard.writeText(note.content).catch(() => {});
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
  }

  // 본문 2줄 미리보기
  function preview(content: string): string {
    return content.replace(/[#*`>\-]/g, '').slice(0, 120);
  }
</script>

<div
  role="button"
  tabindex="0"
  onclick={() => onOpen(note)}
  onkeydown={(e) => e.key === 'Enter' && onOpen(note)}
  class="group relative bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 hover:shadow-md transition-all cursor-pointer"
>
  <!-- 핀 배지 -->
  {#if note.is_pinned}
    <span class="absolute top-2 right-2 text-yellow-500 text-xs">📌</span>
  {/if}

  <!-- 제목 -->
  <h3 class="font-semibold text-gray-900 dark:text-white text-sm mb-1 pr-6 line-clamp-1">
    {note.title}
  </h3>

  <!-- 본문 미리보기 -->
  <p class="text-gray-500 dark:text-gray-400 text-xs line-clamp-2 mb-2">
    {preview(note.content) || '내용 없음'}
  </p>

  <!-- 비고 -->
  {#if note.remark}
    <p class="text-blue-400 text-xs mb-2 line-clamp-1">📎 {note.remark}</p>
  {/if}

  <!-- 태그 -->
  {#if note.tags.length > 0}
    <div class="flex flex-wrap gap-1 mb-2">
      {#each note.tags as tag}
        <span
          class="px-2 py-0.5 text-xs rounded-full text-white"
          style="background-color: {tag.color}"
        >{tag.name}</span>
      {/each}
    </div>
  {/if}

  <!-- 날짜 + 액션 -->
  <div class="flex items-center justify-between">
    <span class="text-gray-400 text-xs">{formatDate(note.updated_at)}</span>
    <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        onclick={handleCopy}
        class="p-1 text-gray-400 hover:text-gray-600 rounded"
        title="복사"
      >📋</button>
      <button
        onclick={handlePin}
        disabled={pinning}
        class="p-1 text-gray-400 hover:text-yellow-500 rounded"
        title={note.is_pinned ? '고정 해제' : '고정'}
      >{note.is_pinned ? '📍' : '📌'}</button>
      <button
        onclick={(e) => { e.stopPropagation(); onEdit(note); }}
        class="p-1 text-gray-400 hover:text-blue-500 rounded"
        title="수정"
      >✏️</button>
      <button
        onclick={handleArchive}
        disabled={archiving}
        class="p-1 text-gray-400 hover:text-orange-500 rounded"
        title="아카이브"
      >📦</button>
      <button
        onclick={handleDelete}
        disabled={deleting}
        class="p-1 text-gray-400 hover:text-red-500 rounded"
        title="삭제"
      >🗑️</button>
    </div>
  </div>
</div>
