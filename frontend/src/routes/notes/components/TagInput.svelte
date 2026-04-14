<script lang="ts">
  import { notesApi } from '$lib/api/notes';
  import type { TagDef } from '$lib/api/notes';
  import { Plus, X } from 'lucide-svelte';
  import TagBadge from './TagBadge.svelte';

  interface Props {
    selectedTagIds: number[];
    allTags: TagDef[];
    onChange: (ids: number[]) => void;
    onTagsRefresh: () => void;
  }

  let { selectedTagIds, allTags, onChange, onTagsRefresh }: Props = $props();

  let query = $state('');
  let showDropdown = $state(false);
  let creating = $state(false);

  // 새 태그 inline 생성 폼
  let showCreateForm = $state(false);
  let newTagColor = $state('#6b7280');

  let filteredTags = $derived(
    allTags.filter(
      (t) =>
        t.name.toLowerCase().includes(query.toLowerCase()) &&
        !selectedTagIds.includes(t.id)
    )
  );

  let selectedTags = $derived(allTags.filter((t) => selectedTagIds.includes(t.id)));

  function selectTag(tag: TagDef) {
    onChange([...selectedTagIds, tag.id]);
    query = '';
    showDropdown = false;
  }

  function removeTag(id: number) {
    onChange(selectedTagIds.filter((i) => i !== id));
  }

  async function createAndSelect() {
    if (!query.trim()) return;
    creating = true;
    try {
      const newTag = await notesApi.createTag({ name: query.trim(), color: newTagColor });
      onTagsRefresh();
      onChange([...selectedTagIds, newTag.id]);
      query = '';
      showDropdown = false;
      showCreateForm = false;
      newTagColor = '#6b7280';
    } catch (e: any) {
      alert(e.message);
    } finally {
      creating = false;
    }
  }
</script>

<div class="relative">
  <!-- 선택된 태그 배지 -->
  {#if selectedTags.length > 0}
    <div class="flex flex-wrap gap-1 mb-2">
      {#each selectedTags as tag}
        <TagBadge {tag} size="sm" removable onRemove={() => removeTag(tag.id)} />
      {/each}
    </div>
  {/if}

  <!-- 입력 -->
  <input
    type="text"
    bind:value={query}
    onfocus={() => (showDropdown = true)}
    onblur={() => setTimeout(() => (showDropdown = false), 150)}
    oninput={() => (showDropdown = true)}
    placeholder="태그 검색 또는 새로 만들기..."
    class="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
      focus:outline-none focus:ring-2 focus:ring-ring/30"
  />

  <!-- 드롭다운 -->
  {#if showDropdown}
    <div class="absolute z-10 w-full mt-1 bg-card border border-border rounded-lg shadow-modal max-h-48 overflow-y-auto flex flex-col">
      <div class="overflow-y-auto flex-1">
        {#each filteredTags as tag}
          <button
            onclick={() => selectTag(tag)}
            class="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted text-left transition-colors"
          >
            <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" style="background-color: {tag.color}"></span>
            {tag.name}
          </button>
        {/each}

        {#if query.trim() && !allTags.some((t) => t.name === query.trim())}
          {#if showCreateForm}
            <!-- inline 생성 폼 -->
            <div class="flex items-center gap-2 px-3 py-2 border-t border-border">
              <input
                type="color"
                bind:value={newTagColor}
                class="h-6 w-6 rounded cursor-pointer border-0 flex-shrink-0"
              />
              <span class="text-sm text-foreground flex-1 truncate">"{query.trim()}"</span>
              <button
                onclick={createAndSelect}
                disabled={creating}
                class="px-2 py-0.5 text-xs rounded bg-primary text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
              >Add</button>
              <button
                onclick={() => (showCreateForm = false)}
                class="px-2 py-0.5 text-xs rounded bg-muted text-muted-foreground flex items-center justify-center"
              ><X size={14} /></button>
            </div>
          {:else}
            <button
              onclick={() => (showCreateForm = true)}
              class="w-full flex items-center gap-1.5 px-3 py-2 text-sm text-primary hover:bg-primary/10 text-left transition-colors"
            >
              <Plus class="w-3.5 h-3.5" />
              "{query.trim()}" 태그 만들기
            </button>
          {/if}
        {/if}

        {#if filteredTags.length === 0 && !query.trim()}
          <p class="px-3 py-2 text-xs text-muted-foreground">사용 가능한 태그 없음</p>
        {/if}
      </div>

      <!-- 닫기 버튼 -->
      <button
        onclick={() => (showDropdown = false)}
        class="w-full text-xs text-muted-foreground border-t border-border px-3 py-1.5 hover:bg-muted text-center transition-colors flex items-center justify-center gap-1"
      ><X size={12} /> 닫기</button>
    </div>
  {/if}
</div>
