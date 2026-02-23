<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { NoteArchive, TagDef } from '$lib/api/notes';
  import { RotateCcw, Trash2, Archive, FileText, ChevronLeft, ChevronRight } from 'lucide-svelte';
  import TagBadge from './TagBadge.svelte';

  let items = $state<NoteArchive[]>([]);
  let tags = $state<TagDef[]>([]);
  let total = $state(0);
  let pages = $state(1);
  let page = $state(1);
  let selectedTag = $state('');
  let loading = $state(false);
  let error = $state('');
  let deleteConfirmId = $state<number | null>(null);

  async function load() {
    loading = true;
    error = '';
    try {
      const [res, tagRes] = await Promise.all([
        notesApi.listArchive({ tag: selectedTag || undefined, page }),
        notesApi.listTags(),
      ]);
      items = res.items;
      total = res.total;
      pages = res.pages;
      tags = tagRes;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function restore(id: number) {
    try {
      await notesApi.restoreArchive(id);
      load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function removeConfirm(id: number) {
    deleteConfirmId = null;
    try {
      await notesApi.deleteArchive(id);
      load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  function selectTag(tagName: string) {
    selectedTag = tagName;
    page = 1;
    load();
  }

  function formatDate(iso: string) {
    return new Date(iso).toLocaleString('ko-KR');
  }

  onMount(load);
</script>

<div class="flex flex-col h-full overflow-hidden">
  <!-- 필터 -->
  <div class="flex flex-col gap-3 p-4 border-b border-border">
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
      <span class="ml-auto text-xs text-muted-foreground self-center">총 {total}개</span>
    </div>
  </div>

  <!-- 목록 -->
  <div class="flex-1 overflow-y-auto p-4">
    {#if loading}
      <div class="space-y-3">
        {#each Array(4) as _}
          <div class="rounded-lg border border-border p-4 space-y-2">
            <div class="animate-skeleton-shimmer h-4 w-1/2 rounded"></div>
            <div class="animate-skeleton-shimmer h-3 w-full rounded"></div>
          </div>
        {/each}
      </div>
    {:else if error}
      <div class="text-center text-destructive text-sm py-8">{error}</div>
    {:else if items.length === 0}
      <div class="flex flex-col items-center justify-center py-16 gap-3">
        <div class="w-14 h-14 bg-muted rounded-2xl flex items-center justify-center">
          <Archive class="w-7 h-7 text-muted-foreground" />
        </div>
        <p class="text-foreground font-medium text-sm">No archived notes</p>
        <p class="text-muted-foreground text-xs">
          {selectedTag ? `"${selectedTag}" 태그에 아카이브된 메모가 없습니다.` : '아카이브된 메모가 없습니다.'}
        </p>
      </div>
    {:else}
      <div class="space-y-2">
        {#each items as item (item.id)}
          <div class="group bg-card border border-border shadow-card hover:shadow-card-hover rounded-lg p-4 transition-all">
            <div class="flex items-start gap-3">
              <!-- FileText 아이콘 -->
              <div class="w-8 h-8 bg-muted rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5">
                <FileText class="w-4 h-4 text-muted-foreground" />
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="font-medium text-foreground text-sm">{item.title}</h3>
                <p class="text-xs text-muted-foreground mt-0.5">아카이브: {formatDate(item.archived_at)}</p>
                <p class="text-muted-foreground text-xs mt-1 line-clamp-2">
                  {item.content.replace(/[#*`>\-]/g, '').slice(0, 100) || '내용 없음'}
                </p>
                {#if item.tags.length > 0}
                  <div class="flex flex-wrap gap-1 mt-2">
                    {#each item.tags as tag}
                      <TagBadge {tag} size="sm" />
                    {/each}
                  </div>
                {/if}
              </div>
              <!-- 액션 버튼 -->
              <div class="flex gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onclick={() => restore(item.id)}
                  class="p-1.5 rounded-lg text-muted-foreground hover:text-success hover:bg-success-light transition-colors"
                  title="복원"
                ><RotateCcw class="w-4 h-4" /></button>

                {#if deleteConfirmId === item.id}
                  <span class="flex gap-1 items-center">
                    <button
                      onclick={() => removeConfirm(item.id)}
                      class="px-2 py-1 text-xs rounded bg-destructive/20 text-destructive border border-destructive/30 hover:bg-destructive/30"
                    >Delete</button>
                    <button
                      onclick={() => (deleteConfirmId = null)}
                      class="px-2 py-1 text-xs rounded bg-muted text-muted-foreground"
                    >Cancel</button>
                  </span>
                {:else}
                  <button
                    onclick={() => (deleteConfirmId = item.id)}
                    class="p-1.5 rounded-lg text-muted-foreground hover:text-destructive hover:bg-error-light transition-colors"
                    title="삭제"
                  ><Trash2 class="w-4 h-4" /></button>
                {/if}
              </div>
            </div>
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
      <span class="text-xs text-muted-foreground">{page} / {pages}</span>
      <button
        onclick={() => { page++; load(); }}
        disabled={page >= pages}
        class="p-2 rounded-lg hover:bg-muted disabled:opacity-40 transition-colors"
      ><ChevronRight class="w-4 h-4" /></button>
    </div>
  {/if}
</div>
