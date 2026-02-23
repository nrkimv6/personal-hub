<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { Note, TagDef } from '$lib/api/notes';
  import { Search, X, ChevronLeft, ChevronRight, FileText } from 'lucide-svelte';
  import NoteCard from './NoteCard.svelte';
  import NoteDetailModal from './NoteDetailModal.svelte';
  import NoteFormModal from './NoteFormModal.svelte';

  let notes = $state<Note[]>([]);
  let tags = $state<TagDef[]>([]);
  let total = $state(0);
  let pages = $state(1);
  let loading = $state(false);
  let error = $state('');

  let search = $state('');
  let selectedTag = $state('');
  let page = $state(1);

  let openNote = $state<Note | null>(null);
  let editNote = $state<Note | null>(null);

  let searchTimer: ReturnType<typeof setTimeout>;

  async function load() {
    loading = true;
    error = '';
    try {
      const [res, tagRes] = await Promise.all([
        notesApi.list({ search: search || undefined, tag: selectedTag || undefined, page }),
        notesApi.listTags(),
      ]);
      notes = res.items;
      total = res.total;
      pages = res.pages;
      tags = tagRes;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function onSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { page = 1; load(); }, 400);
  }

  function selectTag(tagName: string) {
    selectedTag = tagName;
    page = 1;
    load();
  }

  onMount(load);
</script>

<div class="flex flex-col h-full overflow-hidden">
  <!-- 필터 바 -->
  <div class="flex flex-col gap-3 p-4 border-b border-border">
    <!-- 검색 input -->
    <div class="relative">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
      <input
        type="search"
        bind:value={search}
        oninput={onSearchInput}
        placeholder="제목·내용 검색..."
        class="w-full pl-9 pr-8 py-2 text-sm rounded-lg border border-border bg-card text-foreground
          focus:outline-none focus:ring-2 focus:ring-ring/30"
      />
      {#if search}
        <button
          onclick={() => { search = ''; page = 1; load(); }}
          class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        ><X class="w-3.5 h-3.5" /></button>
      {/if}
    </div>

    <!-- 태그 pill 필터 -->
    <div class="flex flex-wrap gap-1.5">
      <button
        onclick={() => selectTag('')}
        class="px-3 py-1.5 text-xs rounded-full border transition-colors
          {selectedTag === ''
            ? 'bg-primary text-primary-foreground border-primary'
            : 'bg-card text-muted-foreground border-border hover:border-primary/50'}"
      >All</button>
      {#each tags as tag}
        <button
          onclick={() => selectTag(tag.name)}
          class="px-3 py-1.5 text-xs rounded-full border transition-colors
            {selectedTag === tag.name
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-card text-muted-foreground border-border hover:border-primary/50'}"
        >{tag.name}</button>
      {/each}
    </div>
  </div>

  <!-- 목록 -->
  <div class="flex-1 overflow-y-auto p-4">
    {#if loading}
      <!-- skeleton shimmer -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {#each Array(6) as _}
          <div class="rounded-lg border border-border p-4 space-y-2">
            <div class="animate-skeleton-shimmer h-4 w-3/4 rounded"></div>
            <div class="animate-skeleton-shimmer h-3 w-full rounded"></div>
            <div class="animate-skeleton-shimmer h-3 w-5/6 rounded"></div>
            <div class="animate-skeleton-shimmer h-3 w-1/4 rounded mt-4"></div>
          </div>
        {/each}
      </div>
    {:else if error}
      <div class="flex flex-col items-center justify-center py-16 gap-3">
        <X class="w-10 h-10 text-destructive/50" />
        <p class="text-destructive text-sm">{error}</p>
        <button
          onclick={load}
          class="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary-hover transition-colors"
        >다시 시도</button>
      </div>
    {:else if notes.length === 0}
      <div class="flex flex-col items-center justify-center py-16 gap-3">
        <div class="w-14 h-14 bg-muted rounded-2xl flex items-center justify-center">
          <FileText class="w-7 h-7 text-muted-foreground" />
        </div>
        <p class="text-foreground font-medium text-sm">No notes yet</p>
        <p class="text-muted-foreground text-xs">
          {selectedTag ? `"${selectedTag}" 태그에 메모가 없습니다.` : '새 메모를 추가해보세요.'}
        </p>
      </div>
    {:else}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {#each notes as note (note.id)}
          <div class="animate-fade-in">
            <NoteCard
              {note}
              onOpen={(n) => (openNote = n)}
              onEdit={(n) => (editNote = n)}
              onRefresh={load}
            />
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- 페이지네이션 -->
  {#if pages > 1}
    <div class="flex items-center justify-center gap-2 p-3 border-t border-border">
      <button
        onclick={() => { page--; load(); }}
        disabled={page <= 1}
        class="p-2 rounded-lg hover:bg-muted disabled:opacity-40 transition-colors"
      ><ChevronLeft class="w-4 h-4" /></button>
      <span class="text-xs text-muted-foreground">{page} / {pages} (총 {total}개)</span>
      <button
        onclick={() => { page++; load(); }}
        disabled={page >= pages}
        class="p-2 rounded-lg hover:bg-muted disabled:opacity-40 transition-colors"
      ><ChevronRight class="w-4 h-4" /></button>
    </div>
  {/if}
</div>

<!-- 상세 모달 -->
{#if openNote}
  <NoteDetailModal
    note={openNote}
    onClose={() => (openNote = null)}
    onEdit={(n) => { openNote = null; editNote = n; }}
    onRefresh={load}
  />
{/if}

<!-- 수정 모달 -->
{#if editNote}
  <NoteFormModal
    mode="edit"
    note={editNote}
    onSave={() => { editNote = null; load(); }}
    onClose={() => (editNote = null)}
  />
{/if}
