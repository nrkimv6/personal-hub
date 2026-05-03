<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { TagDef } from '$lib/api/notes';
  import { X } from 'lucide-svelte';
  import { toast } from '$lib/stores/toast';

  interface Props {
    noteIds: number[];
    onApply: () => void;
    onClose: () => void;
  }

  let { noteIds, onApply, onClose }: Props = $props();

  let tags = $state<TagDef[]>([]);
  let addTagIds = $state<Set<number>>(new Set());
  let removeTagIds = $state<Set<number>>(new Set());
  let loading = $state(false);
  let applying = $state(false);

  function errorMessage(e: unknown): string {
    return e instanceof Error ? e.message : '알 수 없는 오류';
  }

  onMount(async () => {
    loading = true;
    try {
      tags = await notesApi.listTags();
    } finally {
      loading = false;
    }
  });

  function toggleAdd(id: number) {
    const next = new Set(addTagIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
      // 제거 목록에서는 제외
      const r = new Set(removeTagIds);
      r.delete(id);
      removeTagIds = r;
    }
    addTagIds = next;
  }

  function toggleRemove(id: number) {
    const next = new Set(removeTagIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
      // 추가 목록에서는 제외
      const a = new Set(addTagIds);
      a.delete(id);
      addTagIds = a;
    }
    removeTagIds = next;
  }

  async function handleApply() {
    applying = true;
    try {
      await notesApi.bulkTag(noteIds, [...addTagIds], [...removeTagIds]);
      onApply();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      applying = false;
    }
  }
</script>

<!-- 모달 오버레이 -->
<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
  onclick={(e) => { if (e.target === e.currentTarget) onClose(); }}
  onkeydown={(e) => { if (e.key === 'Escape') onClose(); }}
  role="dialog"
  aria-modal="true"
  tabindex="-1"
>
  <div
    class="relative w-80 max-h-[70vh] flex flex-col rounded-xl bg-card border border-border shadow-lg overflow-hidden"
  >
    <!-- 헤더 -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-border">
      <h3 class="text-sm font-semibold text-foreground">
        태그 일괄 편집 ({noteIds.length}개 메모)
      </h3>
      <button onclick={onClose} class="text-muted-foreground hover:text-foreground">
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- 태그 목록 -->
    <div class="flex-1 overflow-y-auto p-4 space-y-2">
      {#if loading}
        <p class="text-xs text-muted-foreground text-center py-4">로딩 중...</p>
      {:else if tags.length === 0}
        <p class="text-xs text-muted-foreground text-center py-4">태그 없음</p>
      {:else}
        <p class="text-xs text-muted-foreground mb-3">각 태그에 추가(+) 또는 제거(-) 액션을 선택하세요.</p>
        {#each tags as tag}
          <div class="flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg hover:bg-muted">
            <div class="flex items-center gap-2 min-w-0">
              <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" style="background:{tag.color}"></span>
              <span class="text-xs text-foreground truncate">{tag.name}</span>
            </div>
            <div class="flex gap-1 flex-shrink-0">
              <!-- 추가 토글 -->
              <button
                onclick={() => toggleAdd(tag.id)}
                class="w-6 h-6 text-xs rounded font-bold transition-colors
                  {addTagIds.has(tag.id)
                    ? 'bg-blue-500 text-white'
                    : 'bg-muted text-muted-foreground hover:bg-blue-100 hover:text-blue-600'}"
                title="추가"
              >+</button>
              <!-- 제거 토글 -->
              <button
                onclick={() => toggleRemove(tag.id)}
                class="w-6 h-6 text-xs rounded font-bold transition-colors
                  {removeTagIds.has(tag.id)
                    ? 'bg-destructive text-white'
                    : 'bg-muted text-muted-foreground hover:bg-red-100 hover:text-destructive'}"
                title="제거"
              >-</button>
            </div>
          </div>
        {/each}
      {/if}
    </div>

    <!-- 푸터 -->
    <div class="flex items-center justify-end gap-2 px-4 py-3 border-t border-border">
      <button
        onclick={onClose}
        class="px-3 py-1.5 text-xs rounded-lg border border-border text-muted-foreground hover:text-foreground transition-colors"
      >취소</button>
      <button
        onclick={handleApply}
        disabled={applying || (addTagIds.size === 0 && removeTagIds.size === 0)}
        class="px-3 py-1.5 text-xs rounded-lg bg-primary text-primary-foreground
          hover:bg-primary-hover disabled:opacity-50 transition-colors"
      >
        {applying ? '처리 중...' : '적용'}
      </button>
    </div>
  </div>
</div>
