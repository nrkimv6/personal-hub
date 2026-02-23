<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';
  import { toast } from '$lib/stores/toast';
  import { Search, Tag, Trash2, Check, X, Loader2, Images, ImagePlus, Eye, FolderOpen, Clipboard } from 'lucide-svelte';

  // 이미지 타입
  interface GalleryImage {
    id: number;
    filename: string;
    file_path: string;
    folder_path: string;
    status: string;
    category: string | null;
    size: number;
    thumbnail: string;
  }

  let images = $state<GalleryImage[]>([]);
  let totalCount = $state(0);
  let loadingImages = $state(true);
  let loadError = $state<string | null>(null);
  let loadingMore = $state(false);

  let selectedImages = $state<number[]>([]);
  let searchQuery = $state('');
  let statusFilter = $state('all');
  let sortBy = $state('date');
  let detailImage = $state<number | null>(null);

  const PAGE_SIZE = 24;
  let currentOffset = $state(0);
  let hasMore = $state(false);

  const statusFilters = ['전체', '대기 중', '매핑됨', 'AI 분류', '승인됨'];
  const statusFilterMap: Record<string, string> = {
    '전체': 'all', '대기 중': 'pending', '매핑됨': 'mapped', 'AI 분류': 'ai_classified', '승인됨': 'approved'
  };

  function getStatusLabel(status: string): string {
    const map: Record<string, string> = {
      pending: '대기', mapped: '매핑됨', ai_classified: 'AI 분류', approved: '승인됨'
    };
    return map[status] ?? status;
  }

  // API 필터 → 쿼리 파라미터 변환
  function buildQuery(offset: number): string {
    const params = new URLSearchParams();
    params.set('limit', String(PAGE_SIZE));
    params.set('skip', String(offset));
    if (statusFilter !== 'all') {
      params.set('status', statusFilter.toLowerCase().replace(' ', '_'));
    }
    if (tagFilter !== null) {
      params.set('tag_id', String(tagFilter));
    }
    if (sortBy === 'date') params.set('order_by', 'extracted_date');
    else if (sortBy === 'name') params.set('order_by', 'id');
    else if (sortBy === 'size') params.set('order_by', 'id');
    params.set('order_dir', 'desc');
    return params.toString();
  }

  // API 응답 → GalleryImage 변환
  function mapFile(f: any): GalleryImage {
    const rawPath = f.file_path || '';
    const parts = rawPath.replace(/\\/g, '/').split('/');
    const filename = parts[parts.length - 1] || `file_${f.id}`;
    const folderPath = parts.slice(0, -1).join('/');
    return {
      id: f.id,
      filename,
      file_path: rawPath,
      folder_path: folderPath,
      status: f.status || 'pending',
      category: f.final_category_id ? String(f.final_category_id) : null,
      size: f.file_size || 0,
      thumbnail: `/api/ic/files/${f.id}/thumbnail`,
    };
  }

  async function openLocalViewer(fileId: number) {
    try {
      const res = await fetchWithTimeout('/api/ic/files/open-local', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: fileId })
      });
      if (!res.ok) {
        const err = await res.json();
        toast.error(err.detail || '뷰어 열기 실패');
      }
    } catch (err: any) {
      toast.error(`뷰어 열기 실패: ${err.message}`);
    }
  }

  async function openFolder(fileId: number) {
    try {
      const res = await fetchWithTimeout('/api/ic/files/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: fileId })
      });
      if (!res.ok) {
        const err = await res.json();
        toast.error(err.detail || '탐색기 열기 실패');
      }
    } catch (err: any) {
      toast.error(`탐색기 열기 실패: ${err.message}`);
    }
  }

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      toast.error('클립보드 복사 실패');
    }
  }

  async function loadImages(reset = false) {
    if (reset) {
      loadingImages = true;
      loadError = null;
      currentOffset = 0;
      images = [];
    } else {
      loadingMore = true;
    }

    try {
      const offset = reset ? 0 : currentOffset;
      const qs = buildQuery(offset);
      const res = await fetchWithTimeout(`/api/ic/files?${qs}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const newImages = (data.files ?? []).map(mapFile);
      if (reset) {
        images = newImages;
      } else {
        images = [...images, ...newImages];
      }
      currentOffset = offset + newImages.length;
      hasMore = newImages.length === PAGE_SIZE;
      totalCount = data.total ?? images.length;
    } catch (err: any) {
      loadError = err.message;
    } finally {
      loadingImages = false;
      loadingMore = false;
    }
  }

  // 필터/정렬 변경 시 재로드
  $effect(() => {
    // statusFilter, sortBy, tagFilter 의존
    void statusFilter;
    void sortBy;
    void tagFilter;
    loadImages(true);
  });

  onMount(() => {
    // $effect가 초기에도 실행되므로 별도 호출 불필요
    void loadTags();
    void loadCategories();
  });

  // 클라이언트 사이드 검색 (이름 필터)
  let filteredImages = $derived(
    searchQuery
      ? images.filter(img => img.filename.toLowerCase().includes(searchQuery.toLowerCase()))
      : images
  );

  let detailData = $derived(
    detailImage !== null ? images.find(img => img.id === detailImage) ?? null : null
  );

  function toggleSelect(id: number) {
    if (selectedImages.includes(id)) {
      selectedImages = selectedImages.filter(x => x !== id);
    } else {
      selectedImages = [...selectedImages, id];
    }
  }

  function openDetail(id: number) {
    detailImage = id;
    void loadDetailTags(id);
  }

  function getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'approved': return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400';
      case 'folder_mapped':
      case 'mapped': return 'bg-primary/10 text-primary';
      case 'ai_classified': return 'bg-amber-500/10 text-amber-700 dark:text-amber-400';
      case 'moved': return 'bg-violet-500/20 text-violet-700';
      default: return 'bg-muted text-muted-foreground';
    }
  }

  function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    if (bytes > 0) return `${(bytes / 1024).toFixed(0)} KB`;
    return '—';
  }

  // === 승인/카테고리/삭제 ===
  async function approveSelected(ids?: number[]) {
    const fileIds = ids ?? selectedImages;
    if (fileIds.length === 0) return;
    try {
      const res = await fetchWithTimeout('/api/ic/files/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: fileIds }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      images = images.map(img =>
        fileIds.includes(img.id) ? { ...img, status: 'approved' } : img
      );
      selectedImages = [];
      detailImage = null;
      toast.success(`${fileIds.length}개 이미지를 승인했습니다.`);
    } catch (err: any) {
      toast.error(`승인 실패: ${err.message}`);
    }
  }

  interface Category { id: number; name: string; full_path: string; parent_id: number | null; children: Category[]; }
  let categories = $state<Category[]>([]);
  let flatCategories = $state<Category[]>([]);
  let categoryMap = $derived(new Map(flatCategories.map((c) => [c.id, c.full_path])));
  let showCategoryPicker = $state(false);

  function flattenCategories(cats: any[]): Category[] {
    let result: Category[] = [];
    for (const cat of cats) {
      result.push({ id: cat.id, name: cat.name, full_path: cat.full_path, parent_id: cat.parent_id ?? null, children: cat.children ?? [] });
      if (cat.children?.length > 0) {
        result = result.concat(flattenCategories(cat.children));
      }
    }
    return result;
  }

  function getCategoryName(categoryId: string | null): string {
    if (!categoryId) return '—';
    const id = Number(categoryId);
    if (isNaN(id)) return categoryId;
    return categoryMap.get(id) ?? `#${categoryId}`;
  }

  // 태그 상태
  interface TagItem { id: number; name: string; }
  let tags = $state<TagItem[]>([]);
  let showTagPicker = $state(false);
  let tagFilter = $state<number | null>(null);  // null = 전체
  let detailTags = $state<TagItem[]>([]);  // 디테일 패널용

  async function loadTags() {
    try {
      const res = await fetchWithTimeout('/api/ic/tags');
      if (res.ok) tags = (await res.json()).tags ?? [];
    } catch { /* ignore */ }
  }

  async function bulkTagFiles(tagName: string) {
    if (selectedImages.length === 0) return;
    const taggedCount = selectedImages.length;
    try {
      const res = await fetchWithTimeout('/api/ic/tags/bulk-tag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: selectedImages, tag_names: [tagName] }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showTagPicker = false;
      await loadTags();
      toast.success(`${taggedCount}개 이미지에 태그를 부여했습니다.`);
    } catch (err: any) {
      toast.error(`태그 부여 실패: ${err.message}`);
    }
  }

  async function loadDetailTags(fileId: number) {
    try {
      const res = await fetchWithTimeout(`/api/ic/tags/files/${fileId}`);
      if (res.ok) detailTags = (await res.json()).tags ?? [];
    } catch { detailTags = []; }
  }

  async function removeDetailTag(fileId: number, tagId: number) {
    try {
      const res = await fetchWithTimeout(`/api/ic/tags/files/${fileId}/${tagId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      detailTags = detailTags.filter(t => t.id !== tagId);
    } catch (err: any) {
      toast.error(`태그 제거 실패: ${err.message}`);
    }
  }

  async function loadCategories() {
    try {
      const res = await fetchWithTimeout('/api/ic/categories?include_tree=true');
      if (res.ok) {
        const data = await res.json();
        categories = data.categories ?? [];
        flatCategories = flattenCategories(categories);
      }
    } catch { /* ignore */ }
  }

  async function assignCategory(categoryId: number) {
    if (selectedImages.length === 0) return;
    try {
      const res = await fetchWithTimeout('/api/ic/files/bulk-classify', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: selectedImages, category_id: categoryId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const categoryStr = String(categoryId);
      images = images.map(img =>
        selectedImages.includes(img.id) ? { ...img, category: categoryStr } : img
      );
      const updatedCount = selectedImages.length;
      selectedImages = [];
      showCategoryPicker = false;
      toast.success(`${updatedCount}개 이미지의 카테고리를 지정했습니다.`);
    } catch (err: any) {
      toast.error(`카테고리 지정 실패: ${err.message}`);
    }
  }

  async function deleteSelected() {
    if (selectedImages.length === 0) return;
    if (!confirm(`선택한 ${selectedImages.length}개 이미지를 삭제하시겠습니까?`)) return;
    try {
      const res = await fetchWithTimeout('/api/ic/files/bulk-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: selectedImages }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const deletedCount = selectedImages.length;
      images = images.filter(img => !selectedImages.includes(img.id));
      totalCount = Math.max(0, totalCount - deletedCount);
      selectedImages = [];
      toast.success(`${deletedCount}개 이미지를 삭제했습니다.`);
    } catch (err: any) {
      toast.error(`삭제 실패: ${err.message}`);
    }
  }

  // === 썸네일 생성 ===
  let thumbGenerating = $state(false);
  let thumbProgress = $state({ processed: 0, total: 0, progress_percent: 0 });
  let thumbPollTimer: ReturnType<typeof setInterval> | null = null;

  async function startThumbnailGeneration() {
    try {
      const res = await fetchWithTimeout('/api/ic/scan/thumbnails', { method: 'POST' });
      if (!res.ok) {
        const data = await res.json();
        toast.error(data.detail || '썸네일 생성 시작 실패');
        return;
      }
      thumbGenerating = true;
      pollThumbnailStatus();
    } catch (err: any) {
      toast.error(`썸네일 생성 오류: ${err.message}`);
    }
  }

  function pollThumbnailStatus() {
    if (thumbPollTimer) clearInterval(thumbPollTimer);
    thumbPollTimer = setInterval(async () => {
      try {
        const res = await fetchWithTimeout('/api/ic/scan/thumbnails/status');
        if (!res.ok) return;
        const data = await res.json();
        thumbProgress = data;
        if (!data.is_running) {
          thumbGenerating = false;
          if (thumbPollTimer) clearInterval(thumbPollTimer);
          thumbPollTimer = null;
          // 완료 후 로컬 캐시버스팅
          const ts = Date.now();
          images = images.map(img => ({
            ...img,
            thumbnail: `/api/ic/files/${img.id}/thumbnail?t=${ts}`
          }));
          toast.success('썸네일 생성이 완료되었습니다.');
        }
      } catch { /* ignore */ }
    }, 1000);
  }

  async function stopThumbnailGeneration() {
    try {
      await fetchWithTimeout('/api/ic/scan/thumbnails/stop', { method: 'POST' });
    } catch { /* ignore */ }
  }

  // 페이지 진입 시 썸네일 상태 체크
  onMount(() => {
    fetchWithTimeout('/api/ic/scan/thumbnails/status')
      .then(r => r.json())
      .then(data => {
        if (data.is_running) {
          thumbGenerating = true;
          thumbProgress = data;
          pollThumbnailStatus();
        }
      })
      .catch(() => {});

    return () => {
      if (thumbPollTimer) clearInterval(thumbPollTimer);
    };
  });
</script>

<div class="space-y-4">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div>
      <div class="flex items-center gap-2">
        <Images class="size-5 text-primary" />
        <h2 class="text-xl font-bold tracking-tight">갤러리</h2>
        <span class="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
          {filteredImages.length}{hasMore ? '+' : ''}이미지
        </span>
      </div>
      <p class="mt-1 text-sm text-muted-foreground">이미지를 탐색하고 분류 상태를 관리합니다.</p>
    </div>
    <div class="flex items-center gap-2">
      {#if thumbGenerating}
        <div class="flex items-center gap-2">
          <div class="flex flex-col items-end gap-0.5">
            <span class="text-[10px] text-muted-foreground">
              썸네일 {thumbProgress.processed}/{thumbProgress.total} ({thumbProgress.progress_percent}%)
            </span>
            <div class="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
              <div
                class="h-full rounded-full bg-primary transition-all"
                style="width: {thumbProgress.progress_percent}%"
              ></div>
            </div>
          </div>
          <button
            onclick={stopThumbnailGeneration}
            class="flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
          >
            <X class="size-3" />
            중지
          </button>
        </div>
      {:else}
        <button
          onclick={startThumbnailGeneration}
          class="flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
        >
          <ImagePlus class="size-3.5" />
          썸네일 생성
        </button>
      {/if}
    </div>
  </div>

  <!-- Filter Bar -->
  <div class="rounded-xl border border-border bg-card p-3">
    <div class="flex flex-wrap items-center gap-3">
      <!-- Search -->
      <div class="relative min-w-[180px] flex-1">
        <Search class="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          placeholder="이미지 검색..."
          bind:value={searchQuery}
          class="h-8 w-full rounded-md border border-border bg-background pl-8 pr-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      <!-- Status Filter Buttons -->
      <div class="flex items-center gap-0.5 rounded-md border border-border bg-muted p-0.5">
        {#each statusFilters as filter}
          {@const filterKey = statusFilterMap[filter] ?? 'all'}
          <button
            onclick={() => (statusFilter = filterKey)}
            class="rounded px-2.5 py-1 text-[11px] font-medium transition-all {statusFilter === filterKey
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
          >
            {filter}
          </button>
        {/each}
      </div>

      <!-- Tag Filter -->
      <select
        bind:value={tagFilter}
        class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        onchange={() => { tagFilter = tagFilter === null ? null : Number(tagFilter); }}
      >
        <option value={null}>전체 태그</option>
        {#each tags as tag}
          <option value={tag.id}>{tag.name}</option>
        {/each}
      </select>

      <!-- Sort -->
      <select
        bind:value={sortBy}
        class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      >
        <option value="date">날짜</option>
        <option value="name">이름</option>
        <option value="size">크기</option>
      </select>
    </div>
  </div>

  <!-- Bulk Action Bar -->
  {#if selectedImages.length > 0}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
      <span class="text-xs font-medium text-primary">{selectedImages.length} 이미지 선택됨</span>
      <div class="mx-1 h-4 w-px bg-border"></div>
      <button onclick={() => { loadCategories(); showCategoryPicker = true; }} class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent">
        <Tag class="size-3" />
        카테고리 지정
      </button>
      <div class="relative">
        <button onclick={() => { loadTags(); showTagPicker = !showTagPicker; }} class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent">
          <Tag class="size-3" />
          태그 부여
        </button>
        {#if showTagPicker}
          <div class="absolute left-0 top-full z-50 mt-1 w-48 rounded-lg border border-border bg-card shadow-lg">
            <div class="p-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">태그 선택</div>
            {#if tags.length === 0}
              <p class="px-3 py-2 text-xs text-muted-foreground">태그 없음</p>
            {:else}
              {#each tags as tag}
                <button
                  onclick={() => bulkTagFiles(tag.name)}
                  class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-foreground hover:bg-accent"
                >
                  <span class="truncate">{tag.name}</span>
                  <span class="ml-auto text-[10px] text-muted-foreground">{tag.usage_count ?? 0}</span>
                </button>
              {/each}
            {/if}
            <div class="border-t border-border p-2">
              <button onclick={() => (showTagPicker = false)} class="w-full rounded px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground">닫기</button>
            </div>
          </div>
        {/if}
      </div>
      <button onclick={() => approveSelected()} class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent">
        <Check class="size-3" />
        승인
      </button>
      <button onclick={deleteSelected} class="flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/10">
        <Trash2 class="size-3" />
        삭제
      </button>
      <button
        onclick={() => (selectedImages = [])}
        class="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <X class="size-3" />
        전체 해제
      </button>
    </div>
  {/if}

  <!-- Loading State -->
  {#if loadingImages}
    <div class="flex items-center justify-center py-16 text-sm text-muted-foreground gap-2">
      <Loader2 class="size-4 animate-spin" />
      이미지 로딩 중...
    </div>
  {:else if loadError}
    <div class="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
      <p class="text-sm font-medium text-destructive mb-2">이미지 로드 실패</p>
      <p class="text-xs text-muted-foreground mb-3">{loadError}</p>
      <button
        onclick={() => loadImages(true)}
        class="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90"
      >
        재시도
      </button>
    </div>
  {:else if filteredImages.length === 0}
    <!-- Empty State -->
    <div class="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div class="rounded-xl bg-muted p-4">
        <Search class="size-8 text-muted-foreground" />
      </div>
      <p class="text-sm font-medium text-foreground">이미지가 없습니다</p>
      <p class="text-xs text-muted-foreground">
        {statusFilter !== 'all' ? '다른 필터를 선택해보세요.' : '먼저 스캔을 실행해주세요.'}
      </p>
    </div>
  {:else}
    <!-- Image Grid -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {#each filteredImages as img (img.id)}
        {@const isSelected = selectedImages.includes(img.id)}
        <div
          role="button"
          tabindex="0"
          class="group relative aspect-square cursor-pointer overflow-hidden rounded-lg border bg-muted transition-all {isSelected
            ? 'ring-2 ring-primary'
            : 'hover:ring-1 hover:ring-primary/50'}"
          onclick={() => openDetail(img.id)}
          onkeydown={(e) => e.key === 'Enter' && openDetail(img.id)}
        >
          <!-- Thumbnail -->
          <img
            src={img.thumbnail}
            alt={img.filename}
            class="absolute inset-0 h-full w-full object-cover transition-transform group-hover:scale-105"
            onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
          />

          <!-- Fallback -->
          <div class="flex h-full w-full items-center justify-center text-[10px] text-muted-foreground/50">
            {img.id}
          </div>

          <!-- Select Checkbox -->
          <button
            class="absolute left-1.5 top-1.5 z-10 flex size-5 items-center justify-center rounded border border-white/50 bg-black/40 opacity-0 transition-all group-hover:opacity-100 {isSelected
              ? '!opacity-100 border-primary bg-primary text-white'
              : ''}"
            onclick={(e) => { e.stopPropagation(); toggleSelect(img.id); }}
            aria-label="Select image"
          >
            {#if isSelected}
              <Check class="size-3" />
            {/if}
          </button>

          <!-- Bottom Gradient Overlay -->
          <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent p-1.5 pt-5">
            <p class="truncate text-[10px] font-medium text-white" title={img.file_path}>{img.filename}</p>
            {#if img.folder_path}
              <p class="truncate text-[9px] text-white/60" title={img.folder_path}>
                {img.folder_path.length > 30 ? '...' + img.folder_path.slice(-27) : img.folder_path}
              </p>
            {/if}
            <span class="mt-0.5 inline-block rounded px-1 py-0.5 text-[9px] font-medium capitalize {getStatusBadgeClass(img.status)}">
              {getStatusLabel(img.status)}
            </span>
            {#if img.category}
              <p class="truncate text-[9px] text-white/70 mt-0.5">{getCategoryName(img.category)}</p>
            {/if}
          </div>
        </div>
      {/each}
    </div>

    <!-- Load More -->
    {#if hasMore}
      <div class="flex justify-center pt-2">
        <button
          onclick={() => loadImages(false)}
          disabled={loadingMore}
          class="inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50 transition-colors"
        >
          {#if loadingMore}
            <Loader2 class="size-4 animate-spin" />
            로딩 중...
          {:else}
            더 보기
          {/if}
        </button>
      </div>
    {/if}
  {/if}
</div>

<!-- Detail Sheet -->
{#if detailImage !== null && detailData !== null}
  <!-- Backdrop -->
  <div
    role="button"
    tabindex="-1"
    class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
    onclick={() => (detailImage = null)}
    onkeydown={(e) => e.key === 'Escape' && (detailImage = null)}
  ></div>

  <!-- Side Panel -->
  <div class="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl">
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold text-foreground">이미지 상세</h2>
      <button
        onclick={() => (detailImage = null)}
        class="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <X class="size-4" />
      </button>
    </div>

    <div class="flex-1 space-y-4 overflow-y-auto p-4">
      <!-- Preview -->
      <div class="relative aspect-video w-full overflow-hidden rounded-lg bg-muted">
        <img
          src={detailData.thumbnail}
          alt={detailData.filename}
          class="h-full w-full object-contain"
          onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
        />
        <div class="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground/50">
          {detailData.filename}
        </div>
      </div>

      <!-- Tags -->
      <div class="rounded-lg border border-border bg-secondary/30 p-3">
        <h3 class="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">태그</h3>
        <div class="flex flex-wrap gap-1.5">
          {#if detailTags.length === 0}
            <p class="text-xs text-muted-foreground">태그 없음</p>
          {:else}
            {#each detailTags as tag}
              <span class="flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-[11px] font-medium text-foreground">
                {tag.name}
                <button
                  onclick={() => detailImage !== null && removeDetailTag(detailImage, tag.id)}
                  class="ml-0.5 flex size-3.5 items-center justify-center rounded-full text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                >
                  <X class="size-2.5" />
                </button>
              </span>
            {/each}
          {/if}
        </div>
      </div>

      <!-- Metadata -->
      <div class="rounded-lg border border-border bg-secondary/30 p-3">
        <h3 class="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">메타데이터</h3>
        <div class="grid grid-cols-2 gap-2">
          <div>
            <p class="text-[10px] text-muted-foreground">파일명</p>
            <p class="truncate text-xs font-medium text-foreground">{detailData.filename}</p>
          </div>
          <div>
            <p class="text-[10px] text-muted-foreground">크기</p>
            <p class="text-xs font-medium text-foreground">{formatSize(detailData.size)}</p>
          </div>
          <div>
            <p class="text-[10px] text-muted-foreground">상태</p>
            <span class="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium capitalize {getStatusBadgeClass(detailData.status)}">
              {getStatusLabel(detailData.status)}
            </span>
          </div>
          <div>
            <p class="text-[10px] text-muted-foreground">카테고리</p>
            <p class="text-xs font-medium text-foreground">{getCategoryName(detailData.category)}</p>
          </div>
        </div>
        <!-- 전체 경로 표시 + 복사 버튼 -->
        {#if detailData.file_path}
          <div class="mt-2">
            <p class="text-[10px] text-muted-foreground mb-0.5">전체 경로</p>
            <div class="flex items-start gap-1">
              <p class="flex-1 break-all text-[10px] font-mono text-foreground">{detailData.file_path}</p>
              <button
                onclick={() => copyToClipboard(detailData!.file_path)}
                class="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                title="경로 복사"
              >
                <Clipboard class="size-3" />
              </button>
            </div>
          </div>
        {/if}
      </div>

      <!-- 로컬 실행 버튼 -->
      <div class="flex gap-2">
        <button
          onclick={() => openLocalViewer(detailData!.id)}
          class="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-xs font-medium text-foreground hover:bg-accent transition-colors"
        >
          <Eye class="size-3.5" />
          뷰어로 열기
        </button>
        <button
          onclick={() => openFolder(detailData!.id)}
          class="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-xs font-medium text-foreground hover:bg-accent transition-colors"
        >
          <FolderOpen class="size-3.5" />
          폴더에서 열기
        </button>
      </div>
    </div>

    <!-- Footer -->
    <div class="flex items-center gap-2 border-t border-border p-3">
      <button onclick={() => detailData && approveSelected([detailData.id])} class="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90">
        <Check class="size-3" />
        승인
      </button>
      <button
        onclick={() => (detailImage = null)}
        class="rounded-md border border-border bg-card px-3 py-2 text-xs font-medium text-foreground hover:bg-accent"
      >
        닫기
      </button>
    </div>
  </div>
{/if}

<!-- Category Picker Modal -->
{#if showCategoryPicker}
  <div
    role="button"
    tabindex="-1"
    class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
    onclick={() => (showCategoryPicker = false)}
    onkeydown={(e) => e.key === 'Escape' && (showCategoryPicker = false)}
  ></div>
  <div class="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-4 shadow-2xl">
    <h3 class="mb-3 text-sm font-semibold text-foreground">카테고리 선택</h3>
    {#if categories.length === 0}
      <p class="text-xs text-muted-foreground">카테고리가 없습니다.</p>
    {:else}
      <div class="max-h-60 space-y-1 overflow-y-auto">
        {#each flatCategories as cat}
          <button
            onclick={() => assignCategory(cat.id)}
            class="flex w-full items-center rounded-md px-3 py-2 text-left text-xs font-medium text-foreground hover:bg-accent"
          >
            {cat.full_path}
          </button>
        {/each}
      </div>
    {/if}
    <button
      onclick={() => (showCategoryPicker = false)}
      class="mt-3 w-full rounded-md border border-border bg-card py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
    >
      취소
    </button>
  </div>
{/if}
