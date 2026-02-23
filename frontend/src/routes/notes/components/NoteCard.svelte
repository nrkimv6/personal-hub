<script lang="ts">
  import type { Note } from '$lib/api/notes';
  import { notesApi } from '$lib/api/notes';
  import { Pin, Star, Copy, Pencil, Archive, Trash2 } from 'lucide-svelte';
  import TagBadge from './TagBadge.svelte';

  interface Props {
    note: Note;
    onOpen: (note: Note) => void;
    onEdit: (note: Note) => void;
    onRefresh: () => void;
    selectMode?: boolean;
    selected?: boolean;
    onToggleSelect?: (id: number) => void;
  }

  let { note, onOpen, onEdit, onRefresh, selectMode = false, selected = false, onToggleSelect }: Props = $props();

  let archiving = $state(false);
  let deleting = $state(false);
  let pinning = $state(false);
  let starring = $state(false);
  let showArchiveConfirm = $state(false);
  let showDeleteConfirm = $state(false);

  async function handleStar(e: Event) {
    e.stopPropagation();
    starring = true;
    try {
      await notesApi.toggleStar(note.id);
      onRefresh();
    } finally {
      starring = false;
    }
  }

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

  async function handleArchiveConfirm(e: Event) {
    e.stopPropagation();
    archiving = true;
    showArchiveConfirm = false;
    try {
      await notesApi.archive(note.id);
      onRefresh();
    } catch (err: any) {
      alert(err.message);
    } finally {
      archiving = false;
    }
  }

  async function handleDeleteConfirm(e: Event) {
    e.stopPropagation();
    deleting = true;
    showDeleteConfirm = false;
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

  function formatTimeAgo(iso: string): string {
    const now = Date.now();
    const diff = now - new Date(iso).getTime();
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  // 본문 2줄 미리보기
  function preview(content: string): string {
    return content.replace(/[#*`>\-]/g, '').slice(0, 120);
  }
</script>

<div
  role="button"
  tabindex="0"
  onclick={() => selectMode ? onToggleSelect?.(note.id) : onOpen(note)}
  onkeydown={(e) => e.key === 'Enter' && (selectMode ? onToggleSelect?.(note.id) : onOpen(note))}
  class="group relative flex flex-col border rounded-lg p-4 transition-all cursor-pointer
    {selected
      ? 'border-blue-400 bg-blue-50 dark:bg-blue-900/10'
      : note.is_pinned
        ? 'bg-pinned border-primary/20'
        : 'bg-card border-border'}
    shadow-card hover:shadow-card-hover"
>
  <!-- 선택 모드 체크박스 -->
  {#if selectMode}
    <span class="absolute top-2 left-2 z-10">
      <input
        type="checkbox"
        checked={selected}
        onclick={(e) => { e.stopPropagation(); onToggleSelect?.(note.id); }}
        class="w-4 h-4 rounded accent-blue-500 cursor-pointer"
      />
    </span>
  {/if}

  <!-- 핀 아이콘 -->
  {#if note.is_pinned && !selectMode}
    <span class="absolute top-2 right-2 text-primary">
      <Pin class="w-3.5 h-3.5 fill-current" />
    </span>
  {/if}

  <!-- 제목 -->
  <h3 class="font-semibold text-foreground text-sm mb-1 pr-6 line-clamp-1 flex items-center gap-1">
    {#if note.is_starred}
      <Star class="w-3.5 h-3.5 text-yellow-400 fill-yellow-400 shrink-0" />
    {/if}
    {note.title}
  </h3>

  <!-- 본문 미리보기 -->
  <p class="text-muted-foreground text-xs line-clamp-2 mb-2">
    {preview(note.content) || '내용 없음'}
  </p>

  <!-- 비고 -->
  {#if note.remark}
    <p class="text-info text-xs mb-2 truncate max-w-[120px]">{note.remark}</p>
  {/if}

  <!-- 태그 -->
  {#if note.tags.length > 0}
    <div class="flex flex-wrap gap-1 mb-2">
      {#each note.tags as tag}
        <TagBadge {tag} size="sm" />
      {/each}
    </div>
  {/if}

  <!-- 날짜 -->
  <div class="flex items-center justify-between mt-auto">
    <span class="text-muted-foreground text-xs">{formatTimeAgo(note.updated_at)}</span>
  </div>

  <!-- hover actions bar -->
  <div
    class="absolute bottom-0 left-0 right-0 flex items-center justify-around px-2 py-1.5
      bg-card/95 backdrop-blur-sm border-t border-border rounded-b-lg
      opacity-0 group-hover:opacity-100 transition-opacity"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
    role="toolbar"
  >
    <button
      onclick={handleCopy}
      class="p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-muted transition-colors"
      title="복사"
    ><Copy class="w-3.5 h-3.5" /></button>

    <button
      onclick={handleStar}
      disabled={starring}
      class="p-1.5 rounded-md hover:bg-muted transition-colors
        {note.is_starred ? 'text-yellow-400' : 'text-muted-foreground hover:text-foreground'}"
      title={note.is_starred ? '별표 해제' : '별표'}
    ><Star class="w-3.5 h-3.5 {note.is_starred ? 'fill-current' : ''}" /></button>

    <button
      onclick={handlePin}
      disabled={pinning}
      class="p-1.5 rounded-md hover:bg-muted transition-colors
        {note.is_pinned ? 'text-primary' : 'text-muted-foreground hover:text-foreground'}"
      title={note.is_pinned ? '고정 해제' : '고정'}
    ><Pin class="w-3.5 h-3.5 {note.is_pinned ? 'fill-current' : ''}" /></button>

    <button
      onclick={(e) => { e.stopPropagation(); onEdit(note); }}
      class="p-1.5 text-muted-foreground hover:text-foreground rounded-md hover:bg-muted transition-colors"
      title="수정"
    ><Pencil class="w-3.5 h-3.5" /></button>

    {#if showArchiveConfirm}
      <span class="flex gap-1 text-xs">
        <button
          onclick={handleArchiveConfirm}
          class="px-1.5 py-0.5 bg-warning/20 text-warning rounded"
        >확인</button>
        <button
          onclick={(e) => { e.stopPropagation(); showArchiveConfirm = false; }}
          class="px-1.5 py-0.5 bg-muted text-muted-foreground rounded"
        >취소</button>
      </span>
    {:else}
      <button
        onclick={(e) => { e.stopPropagation(); showArchiveConfirm = true; }}
        disabled={archiving}
        class="p-1.5 text-muted-foreground hover:text-warning rounded-md hover:bg-muted transition-colors"
        title="아카이브"
      ><Archive class="w-3.5 h-3.5" /></button>
    {/if}

    {#if showDeleteConfirm}
      <span class="flex gap-1 text-xs">
        <button
          onclick={handleDeleteConfirm}
          class="px-1.5 py-0.5 bg-destructive/20 text-destructive rounded"
        >삭제</button>
        <button
          onclick={(e) => { e.stopPropagation(); showDeleteConfirm = false; }}
          class="px-1.5 py-0.5 bg-muted text-muted-foreground rounded"
        >취소</button>
      </span>
    {:else}
      <button
        onclick={(e) => { e.stopPropagation(); showDeleteConfirm = true; }}
        disabled={deleting}
        class="p-1.5 text-muted-foreground hover:text-destructive rounded-md hover:bg-muted transition-colors"
        title="삭제"
      ><Trash2 class="w-3.5 h-3.5" /></button>
    {/if}
  </div>
</div>
