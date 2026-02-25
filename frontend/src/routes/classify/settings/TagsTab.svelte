<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';
  import { Tags, Search, Plus, Trash2, X, Tag, Loader2, FolderSymlink, Save } from 'lucide-svelte';
  import { toast } from '$lib/stores/toast';

  interface TagItem {
    id: number;
    name: string;
    usage_count: number;
    created_at: string | null;
    folder_template?: string | null;
    folder_action?: string | null;
  }

  // 폴더 규칙 편집 상태
  let editingFolderRule = $state(false);
  let folderRuleForm = $state({ folder_template: '', folder_action: 'move' });
  let savingFolderRule = $state(false);

  let tags = $state<TagItem[]>([]);
  let loadingTags = $state(true);
  let tagsError = $state<string | null>(null);

  let searchQuery = $state('');
  let selectedTag = $state<TagItem | null>(null);
  let showNewTagInput = $state(false);
  let newTagName = $state('');
  let creatingTag = $state(false);
  let deletingTagId = $state<number | null>(null);

  // 필터된 태그 목록
  let filteredTags = $derived(
    searchQuery
      ? tags.filter(t => t.name.toLowerCase().includes(searchQuery.toLowerCase()))
      : tags
  );

  // 최대 usage_count (바 너비 계산용)
  let maxCount = $derived(Math.max(...tags.map(t => t.usage_count), 1));

  async function loadTags() {
    loadingTags = true;
    tagsError = null;
    try {
      const res = await fetchWithTimeout('/api/ic/tags/?sort_by=usage&limit=100');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      tags = data.tags ?? [];
    } catch (err: any) {
      tagsError = err.message;
    } finally {
      loadingTags = false;
    }
  }

  async function createTag() {
    const name = newTagName.trim();
    if (!name) return;
    creatingTag = true;
    try {
      const res = await fetchWithTimeout('/api/ic/tags/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showNewTagInput = false;
      newTagName = '';
      await loadTags(); // 재로드
    } catch (err: any) {
      toast.error(`태그 생성 실패: ${err.message}`);
    } finally {
      creatingTag = false;
    }
  }

  async function deleteTag(tag: TagItem) {
    if (!confirm(`태그 "${tag.name}"를 삭제하시겠습니까?`)) return;
    deletingTagId = tag.id;
    try {
      const res = await fetchWithTimeout(`/api/ic/tags/${tag.id}?force=true`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (selectedTag?.id === tag.id) selectedTag = null;
      await loadTags();
    } catch (err: any) {
      toast.error(`태그 삭제 실패: ${err.message}`);
    } finally {
      deletingTagId = null;
    }
  }

  async function saveFolderRule() {
    if (!selectedTag) return;
    savingFolderRule = true;
    try {
      const res = await fetchWithTimeout(`/api/ic/tags/${selectedTag.id}/folder-rule`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          folder_template: folderRuleForm.folder_template || null,
          folder_action: folderRuleForm.folder_action || null,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      editingFolderRule = false;
      // 태그 목록 갱신
      await loadTags();
      // selectedTag 갱신
      const updated = tags.find(t => t.id === selectedTag!.id);
      if (updated) selectedTag = updated;
    } catch (err: any) {
      toast.error(`폴더 규칙 저장 실패: ${err.message}`);
    } finally {
      savingFolderRule = false;
    }
  }

  onMount(() => {
    loadTags();
  });
</script>

<div class="space-y-6">
  <!-- 헤더 -->
  <div class="flex items-center justify-between">
    <div>
      <div class="flex items-center gap-2">
        <Tags class="size-5 text-primary" />
        <h2 class="text-xl font-bold tracking-tight">태그 관리</h2>
      </div>
      <p class="mt-1 text-sm text-muted-foreground">이미지 라이브러리의 태그를 구성하고 관리합니다</p>
    </div>
  </div>

  <!-- Two-panel layout -->
  <div class="flex flex-col gap-6 lg:flex-row">
    <!-- Panel A: Tag Directory -->
    <div class="flex flex-shrink-0 flex-col rounded-xl border border-border bg-card lg:w-80">
      <div class="border-b border-border p-3">
        <h2 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">태그 목록</h2>
        <!-- Search -->
        <div class="relative">
          <Search class="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="태그 검색..."
            bind:value={searchQuery}
            class="h-8 w-full rounded-md border border-border bg-background pl-8 pr-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      <!-- Tag List -->
      <div class="flex-1 divide-y divide-border overflow-y-auto">
        {#if loadingTags}
          <div class="flex items-center justify-center py-8 gap-2 text-xs text-muted-foreground">
            <Loader2 class="size-3.5 animate-spin" />
            로딩 중...
          </div>
        {:else if tagsError}
          <div class="flex flex-col items-center justify-center py-8 gap-2 text-xs text-muted-foreground">
            <p class="text-destructive">로드 실패: {tagsError}</p>
            <button onclick={loadTags} class="text-primary hover:underline">재시도</button>
          </div>
        {:else if filteredTags.length === 0}
          <div class="flex items-center justify-center py-8 text-xs text-muted-foreground">
            {searchQuery ? '검색 결과 없음' : '태그 없음'}
          </div>
        {:else}
          {#each filteredTags as tag (tag.id)}
            {@const isSelected = selectedTag?.id === tag.id}
            <button
              onclick={() => (selectedTag = isSelected ? null : tag)}
              class="group flex w-full flex-col px-3 py-2.5 text-left transition-colors {isSelected
                ? 'border-l-2 border-primary bg-primary/10'
                : 'border-l-2 border-transparent hover:bg-accent'}"
            >
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <Tag class="size-3 {isSelected ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'}" />
                  <span class="text-xs font-medium {isSelected ? 'text-primary' : 'text-foreground'}">{tag.name}</span>
                </div>
                <span class="text-[10px] text-muted-foreground">{tag.usage_count.toLocaleString()}</span>
              </div>
              <!-- Mini Usage Bar -->
              <div class="mt-1.5 h-0.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary/30"
                  style="width: {(tag.usage_count / maxCount) * 100}%"
                ></div>
              </div>
            </button>
          {/each}
        {/if}
      </div>

      <!-- Create New Tag -->
      <div class="border-t border-border p-3">
        {#if showNewTagInput}
          <div class="flex gap-2">
            <input
              type="text"
              placeholder="태그 이름..."
              bind:value={newTagName}
              disabled={creatingTag}
              class="h-8 flex-1 rounded-md border border-border bg-background px-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
              onkeydown={(e) => {
                if (e.key === 'Enter') createTag();
                if (e.key === 'Escape') { showNewTagInput = false; newTagName = ''; }
              }}
            />
            <button
              onclick={() => { showNewTagInput = false; newTagName = ''; }}
              disabled={creatingTag}
              class="flex size-8 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent disabled:opacity-50"
            >
              <X class="size-3.5" />
            </button>
            <button
              onclick={createTag}
              disabled={creatingTag || !newTagName.trim()}
              class="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {#if creatingTag}
                <Loader2 class="size-3.5 animate-spin" />
              {:else}
                <Plus class="size-3.5" />
              {/if}
            </button>
          </div>
        {:else}
          <button
            onclick={() => (showNewTagInput = true)}
            class="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary transition-colors"
          >
            <Plus class="size-3.5" />
            새 태그 만들기
          </button>
        {/if}
      </div>
    </div>

    <!-- Panel B: Tag Detail -->
    <div class="flex flex-1 flex-col rounded-xl border border-border bg-card">
      {#if selectedTag === null}
        <!-- Empty State -->
        <div class="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
          <div class="flex size-14 items-center justify-center rounded-xl bg-muted">
            <Tag class="size-6 text-muted-foreground" />
          </div>
          <div>
            <p class="text-sm font-medium text-foreground">태그를 선택하세요</p>
            <p class="mt-1 text-xs text-muted-foreground">목록에서 태그를 선택하면 정보를 확인할 수 있습니다</p>
          </div>
        </div>
      {:else}
        <!-- Tag Header -->
        <div class="flex items-center justify-between border-b border-border px-4 py-3">
          <div class="flex items-center gap-2">
            <Tag class="size-4 text-primary" />
            <h2 class="text-sm font-semibold text-foreground">{selectedTag.name}</h2>
            <span class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
              {selectedTag.usage_count.toLocaleString()}번 사용
            </span>
          </div>
          <button
            onclick={() => deleteTag(selectedTag!)}
            disabled={deletingTagId === selectedTag.id}
            class="flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
          >
            {#if deletingTagId === selectedTag.id}
              <Loader2 class="size-3 animate-spin" />
            {:else}
              <Trash2 class="size-3" />
            {/if}
            태그 삭제
          </button>
        </div>

        <!-- Tag Info -->
        <div class="p-4 space-y-4">
          <div class="rounded-lg border border-border bg-secondary/30 p-4 space-y-2 text-xs">
            <div class="flex justify-between">
              <span class="text-muted-foreground">태그 ID</span>
              <span class="font-medium text-foreground">{selectedTag.id}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-muted-foreground">사용 횟수</span>
              <span class="font-medium text-foreground">{selectedTag.usage_count.toLocaleString()}</span>
            </div>
            {#if selectedTag.created_at}
              <div class="flex justify-between">
                <span class="text-muted-foreground">생성일</span>
                <span class="font-medium text-foreground">{selectedTag.created_at.slice(0, 10)}</span>
              </div>
            {/if}
          </div>

          <!-- 폴더 규칙 섹션 -->
          <div class="rounded-lg border border-border bg-card p-4">
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <FolderSymlink class="size-4 text-primary" />
                <h3 class="text-sm font-semibold text-foreground">폴더 규칙</h3>
              </div>
              {#if !editingFolderRule}
                <button
                  onclick={() => {
                    folderRuleForm = {
                      folder_template: selectedTag!.folder_template ?? '',
                      folder_action: selectedTag!.folder_action ?? 'move',
                    };
                    editingFolderRule = true;
                  }}
                  class="flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
                >
                  <Save class="size-3" />
                  편집
                </button>
              {/if}
            </div>

            {#if editingFolderRule}
              <div class="space-y-3">
                <div>
                  <label class="mb-1 block text-xs font-medium text-muted-foreground">
                    폴더 경로 템플릿
                  </label>
                  <input
                    type="text"
                    bind:value={folderRuleForm.folder_template}
                    placeholder="{category}/{year}/{tag}"
                    class="h-8 w-full rounded-md border border-border bg-background px-3 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <p class="mt-1 text-[10px] text-muted-foreground">
                    사용 가능 변수: {'{category}'}, {'{year}'}, {'{month}'}, {'{tag}'}
                  </p>
                </div>
                <div>
                  <label class="mb-1 block text-xs font-medium text-muted-foreground">
                    파일 처리 방식
                  </label>
                  <div class="flex gap-1">
                    {#each [['move', '이동'], ['copy', '복사'], ['link', '링크']] as [val, label]}
                      <button
                        onclick={() => (folderRuleForm.folder_action = val)}
                        class="rounded-md border px-3 py-1 text-xs transition-colors {folderRuleForm.folder_action === val
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border text-muted-foreground hover:bg-accent'}"
                      >
                        {label}
                      </button>
                    {/each}
                  </div>
                </div>
                <div class="flex justify-end gap-2">
                  <button
                    onclick={() => (editingFolderRule = false)}
                    class="rounded-md border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-accent"
                  >
                    취소
                  </button>
                  <button
                    onclick={saveFolderRule}
                    disabled={savingFolderRule}
                    class="flex items-center gap-1 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    {#if savingFolderRule}
                      <Loader2 class="size-3 animate-spin" />
                    {:else}
                      <Save class="size-3" />
                    {/if}
                    저장
                  </button>
                </div>
              </div>
            {:else}
              <div class="space-y-2 text-xs">
                {#if selectedTag.folder_template}
                  <div class="flex justify-between">
                    <span class="text-muted-foreground">경로 템플릿</span>
                    <code class="rounded bg-muted px-2 py-0.5 font-mono text-[11px]">{selectedTag.folder_template}</code>
                  </div>
                  <div class="flex justify-between">
                    <span class="text-muted-foreground">처리 방식</span>
                    <span class="font-medium">{selectedTag.folder_action ?? 'move'}</span>
                  </div>
                {:else}
                  <p class="text-center text-muted-foreground">폴더 규칙이 설정되지 않았습니다.</p>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
