<script lang="ts">
  import { Tags, Search, Plus, Trash2, X, Tag } from 'lucide-svelte';

  let searchQuery = $state('');
  let selectedTag = $state<string | null>(null);
  let showNewTagInput = $state(false);
  let newTagName = $state('');

  const mockTags = [
    { name: 'travel', count: 234, color: 'primary' },
    { name: 'family', count: 189, color: 'success' },
    { name: 'nature', count: 156, color: 'warning' },
    { name: 'food', count: 98, color: 'destructive' },
    { name: 'work', count: 67, color: 'muted' },
    { name: 'birthday', count: 45, color: 'primary' },
    { name: 'vacation', count: 38, color: 'success' },
    { name: 'pets', count: 29, color: 'warning' },
  ];

  const filteredTags = $derived(
    searchQuery
      ? mockTags.filter(t => t.name.includes(searchQuery.toLowerCase()))
      : mockTags
  );

  const maxCount = $derived(Math.max(...mockTags.map(t => t.count)));

  const tagImages = $derived(
    selectedTag
      ? Array.from({ length: 12 }, (_, i) => ({
          id: i + 1,
          filename: `photo_${String(i + 1).padStart(3, '0')}.jpg`
        }))
      : []
  );

  function getTagBadgeClass(color: string): string {
    switch (color) {
      case 'success': return 'bg-green-500/10 text-green-600 dark:text-green-400';
      case 'warning': return 'bg-yellow-500/10 text-yellow-700 dark:text-yellow-400';
      case 'destructive': return 'bg-destructive/10 text-destructive';
      default: return 'bg-primary/10 text-primary';
    }
  }
</script>

<div class="space-y-6">
  <!-- Header -->
  <div class="flex items-start gap-3">
    <div class="flex size-10 items-center justify-center rounded-xl bg-primary/10">
      <Tags class="size-5 text-primary" />
    </div>
    <div>
      <h1 class="text-2xl font-bold text-foreground">Tag Management</h1>
      <p class="text-sm text-muted-foreground">Organize and manage image tags across your library</p>
    </div>
  </div>

  <!-- Two-panel layout -->
  <div class="flex flex-col gap-6 lg:flex-row">
    <!-- Panel A: Tag Directory -->
    <div class="flex flex-shrink-0 flex-col rounded-xl border border-border bg-card lg:w-80">
      <div class="border-b border-border p-3">
        <h2 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Tag Directory</h2>
        <!-- Search -->
        <div class="relative">
          <Search class="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search tags..."
            bind:value={searchQuery}
            class="h-8 w-full rounded-md border border-border bg-background pl-8 pr-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      <!-- Tag List -->
      <div class="flex-1 divide-y divide-border overflow-y-auto">
        {#if filteredTags.length === 0}
          <div class="flex items-center justify-center py-8 text-xs text-muted-foreground">
            No tags found
          </div>
        {:else}
          {#each filteredTags as tag}
            {@const isSelected = selectedTag === tag.name}
            <button
              onclick={() => (selectedTag = isSelected ? null : tag.name)}
              class="group flex w-full flex-col px-3 py-2.5 text-left transition-colors {isSelected
                ? 'border-l-2 border-primary bg-primary/10'
                : 'border-l-2 border-transparent hover:bg-accent'}"
            >
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <Tag class="size-3 {isSelected ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground'}" />
                  <span class="text-xs font-medium {isSelected ? 'text-primary' : 'text-foreground'}">{tag.name}</span>
                </div>
                <span class="text-[10px] text-muted-foreground">{tag.count.toLocaleString()}</span>
              </div>
              <!-- Mini Usage Bar -->
              <div class="mt-1.5 h-0.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary/30"
                  style="width: {(tag.count / maxCount) * 100}%"
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
              placeholder="Tag name..."
              bind:value={newTagName}
              class="h-8 flex-1 rounded-md border border-border bg-background px-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              onkeydown={(e) => {
                if (e.key === 'Enter') { showNewTagInput = false; newTagName = ''; }
                if (e.key === 'Escape') { showNewTagInput = false; newTagName = ''; }
              }}
            />
            <button
              onclick={() => { showNewTagInput = false; newTagName = ''; }}
              class="flex size-8 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent"
            >
              <X class="size-3.5" />
            </button>
          </div>
        {:else}
          <button
            onclick={() => (showNewTagInput = true)}
            class="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary transition-colors"
          >
            <Plus class="size-3.5" />
            Create New Tag
          </button>
        {/if}
      </div>
    </div>

    <!-- Panel B: Tag Images -->
    <div class="flex flex-1 flex-col rounded-xl border border-border bg-card">
      {#if selectedTag === null}
        <!-- Empty State -->
        <div class="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
          <div class="flex size-14 items-center justify-center rounded-xl bg-muted">
            <Tag class="size-6 text-muted-foreground" />
          </div>
          <div>
            <p class="text-sm font-medium text-foreground">Select a tag to view images</p>
            <p class="mt-1 text-xs text-muted-foreground">Choose a tag from the directory to browse its images</p>
          </div>
        </div>
      {:else}
        <!-- Tag Header -->
        <div class="flex items-center justify-between border-b border-border px-4 py-3">
          <div class="flex items-center gap-2">
            <Tag class="size-4 text-primary" />
            <h2 class="text-sm font-semibold text-foreground">{selectedTag}</h2>
            <span class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
              {tagImages.length} images
            </span>
          </div>
          <button
            class="flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
          >
            <Trash2 class="size-3" />
            Delete Tag
          </button>
        </div>

        <!-- Image Grid -->
        <div class="p-4">
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {#each tagImages as img (img.id)}
              <div class="group relative aspect-square overflow-hidden rounded-lg bg-muted">
                <!-- Placeholder -->
                <div class="flex h-full w-full items-center justify-center bg-gradient-to-br from-muted to-muted/50 text-[10px] text-muted-foreground/50">
                  {img.id}
                </div>

                <!-- Hover: Remove X button -->
                <button
                  class="absolute right-1 top-1 flex size-5 items-center justify-center rounded-full bg-black/60 text-white opacity-0 transition-opacity group-hover:opacity-100 hover:bg-destructive"
                  aria-label="Remove tag from image"
                >
                  <X class="size-3" />
                </button>

                <!-- Bottom filename overlay -->
                <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent p-1.5">
                  <p class="truncate text-[10px] text-white">{img.filename}</p>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
