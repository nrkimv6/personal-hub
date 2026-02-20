<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { NoteArchive, TagDef } from '$lib/api/notes';

  let items = $state<NoteArchive[]>([]);
  let tags = $state<TagDef[]>([]);
  let total = $state(0);
  let pages = $state(1);
  let page = $state(1);
  let selectedTag = $state('');
  let loading = $state(false);
  let error = $state('');

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
    if (!confirm('메모를 복원하시겠습니까?')) return;
    try {
      await notesApi.restoreArchive(id);
      load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  async function remove(id: number) {
    if (!confirm('영구 삭제하시겠습니까? 되돌릴 수 없습니다.')) return;
    try {
      await notesApi.deleteArchive(id);
      load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  function formatDate(iso: string) {
    return new Date(iso).toLocaleString('ko-KR');
  }

  onMount(load);
</script>

<div class="flex flex-col h-full overflow-hidden">
  <!-- 필터 -->
  <div class="flex gap-2 p-4 border-b border-gray-200 dark:border-gray-700">
    <select
      bind:value={selectedTag}
      onchange={() => { page = 1; load(); }}
      class="px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700"
    >
      <option value="">전체 태그</option>
      {#each tags as tag}
        <option value={tag.name}>{tag.name}</option>
      {/each}
    </select>
    <span class="ml-auto text-sm text-gray-400 self-center">총 {total}개</span>
  </div>

  <!-- 목록 -->
  <div class="flex-1 overflow-y-auto p-4">
    {#if loading}
      <div class="text-center text-gray-400 py-8">불러오는 중...</div>
    {:else if error}
      <div class="text-center text-red-400 py-8">{error}</div>
    {:else if items.length === 0}
      <div class="text-center text-gray-400 py-8">아카이브된 메모가 없습니다.</div>
    {:else}
      <div class="space-y-3">
        {#each items as item (item.id)}
          <div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
            <div class="flex items-start justify-between gap-3">
              <div class="flex-1 min-w-0">
                <h3 class="font-medium text-gray-900 dark:text-white text-sm">{item.title}</h3>
                <p class="text-xs text-gray-400 mt-0.5">아카이브: {formatDate(item.archived_at)}</p>
                <p class="text-gray-500 dark:text-gray-400 text-xs mt-1 line-clamp-2">
                  {item.content.replace(/[#*`>\-]/g, '').slice(0, 100) || '내용 없음'}
                </p>
                {#if item.tags.length > 0}
                  <div class="flex flex-wrap gap-1 mt-2">
                    {#each item.tags as tag}
                      <span class="px-2 py-0.5 text-xs rounded-full text-white" style="background-color: {tag.color}">{tag.name}</span>
                    {/each}
                  </div>
                {/if}
              </div>
              <div class="flex gap-1 shrink-0">
                <button
                  onclick={() => restore(item.id)}
                  class="px-3 py-1.5 text-xs rounded-lg border text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20"
                >복원</button>
                <button
                  onclick={() => remove(item.id)}
                  class="px-3 py-1.5 text-xs rounded-lg border text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                >삭제</button>
              </div>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- 페이지네이션 -->
  {#if pages > 1}
    <div class="flex items-center justify-center gap-3 p-3 border-t border-gray-200 dark:border-gray-700">
      <button onclick={() => { page--; load(); }} disabled={page <= 1} class="px-3 py-1 text-sm rounded border disabled:opacity-40">이전</button>
      <span class="text-sm text-gray-600 dark:text-gray-400">{page} / {pages}</span>
      <button onclick={() => { page++; load(); }} disabled={page >= pages} class="px-3 py-1 text-sm rounded border disabled:opacity-40">다음</button>
    </div>
  {/if}
</div>
