<script lang="ts">
  import type { Category } from '../lib/categoryUtils';

  interface Props {
    /** 트리 구조 카테고리 (빈 상태 체크용) */
    categories: Category[];
    /** 플랫 카테고리 목록 (선택 리스트 표시용) */
    flatCategories: Category[];
    /** 카테고리 선택 시 호출 */
    onSelect: (categoryId: number) => void;
    /** 모달 닫기 */
    onClose: () => void;
    /** 모달 제목 (기본값: '카테고리 선택') */
    title?: string;
  }

  const { categories, flatCategories, onSelect, onClose, title = '카테고리 선택' }: Props = $props();
</script>

<div
  role="button"
  tabindex="-1"
  class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
  onclick={onClose}
  onkeydown={(e) => e.key === 'Escape' && onClose()}
></div>
<div
  class="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-4 shadow-2xl"
>
  <h3 class="mb-3 text-sm font-semibold text-foreground">{title}</h3>
  {#if categories.length === 0}
    <p class="text-xs text-muted-foreground">카테고리가 없습니다.</p>
  {:else}
    <div class="max-h-60 space-y-1 overflow-y-auto">
      {#each flatCategories as cat}
        <button
          onclick={() => onSelect(cat.id)}
          class="flex w-full items-center rounded-md px-3 py-2 text-left text-xs font-medium text-foreground hover:bg-accent"
        >
          {cat.full_path}
        </button>
      {/each}
    </div>
  {/if}
  <button
    onclick={onClose}
    class="mt-3 w-full rounded-md border border-border bg-card py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
  >
    취소
  </button>
</div>
