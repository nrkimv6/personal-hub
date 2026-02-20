<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { Note, TagDef } from '$lib/api/notes';
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

  function onTagChange() {
    page = 1;
    load();
  }

  onMount(load);
</script>

<div class="flex flex-col h-full overflow-hidden">
  <!-- 필터 바 -->
  <div class="flex gap-2 p-4 border-b border-gray-200 dark:border-gray-700">
    <input
      type="search"
      bind:value={search}
      oninput={onSearchInput}
      placeholder="제목·내용 검색..."
      class="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
    />
    <select
      bind:value={selectedTag}
      onchange={onTagChange}
      class="px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
    >
      <option value="">전체 태그</option>
      {#each tags as tag}
        <option value={tag.name}>{tag.name} ({tag.note_count})</option>
      {/each}
    </select>
  </div>

  <!-- 목록 -->
  <div class="flex-1 overflow-y-auto p-4">
    {#if loading}
      <div class="text-center text-gray-400 py-8">불러오는 중...</div>
    {:else if error}
      <div class="text-center text-red-400 py-8">{error}</div>
    {:else if notes.length === 0}
      <div class="text-center text-gray-400 py-8">메모가 없습니다.</div>
    {:else}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {#each notes as note (note.id)}
          <NoteCard
            {note}
            onOpen={(n) => (openNote = n)}
            onEdit={(n) => (editNote = n)}
            onRefresh={load}
          />
        {/each}
      </div>
    {/if}
  </div>

  <!-- 페이지네이션 -->
  {#if pages > 1}
    <div class="flex items-center justify-center gap-3 p-3 border-t border-gray-200 dark:border-gray-700">
      <button
        onclick={() => { page--; load(); }}
        disabled={page <= 1}
        class="px-3 py-1 text-sm rounded border disabled:opacity-40"
      >이전</button>
      <span class="text-sm text-gray-600 dark:text-gray-400">{page} / {pages} (총 {total}개)</span>
      <button
        onclick={() => { page++; load(); }}
        disabled={page >= pages}
        class="px-3 py-1 text-sm rounded border disabled:opacity-40"
      >다음</button>
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
