<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { flattenNavEntries, type FlatNavItem } from '$lib/navigation';
  import { X } from 'lucide-svelte';

  export let selectedMenuId: string | null = null;
  export let onSelect: (menuId: string | null) => void = () => {};

  let searchQuery = '';
  let focusedIndex = -1;
  let isMobile = false;

  // NavGroup 내부 아이템 포함 전체 목록
  const allItems: FlatNavItem[] = flattenNavEntries();

  $: filteredItems = searchQuery.trim()
    ? allItems.filter((e) =>
        e.label.toLowerCase().includes(searchQuery.trim().toLowerCase())
      )
    : allItems;

  // 카테고리별 그룹핑
  $: groupedFiltered = (() => {
    const groups: { category: string | null; items: FlatNavItem[] }[] = [];
    let currentCategory: string | null = undefined as unknown as string | null;
    for (const item of filteredItems) {
      const cat = item.category ?? null;
      if (cat !== currentCategory) {
        groups.push({ category: cat, items: [item] });
        currentCategory = cat;
      } else {
        groups[groups.length - 1].items.push(item);
      }
    }
    return groups;
  })();

  // 플랫 목록 (키보드 탐색용)
  $: flatList = ['__clear__', ...filteredItems.map((e) => e.id)];

  // 모바일 감지 (640px 미만 = sm 이하)
  let mq: MediaQueryList;
  onMount(() => {
    mq = window.matchMedia('(max-width: 639px)');
    isMobile = mq.matches;
    const handler = (e: MediaQueryListEvent) => { isMobile = e.matches; };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  });

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      focusedIndex = Math.min(focusedIndex + 1, flatList.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      focusedIndex = Math.max(focusedIndex - 1, 0);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (focusedIndex >= 0) {
        const id = flatList[focusedIndex];
        if (id === '__clear__') {
          onSelect(null);
        } else {
          onSelect(id);
        }
      }
    } else if (e.key === 'Escape') {
      onSelect(selectedMenuId); // 변경 없이 닫기
    }
  }

  function selectItem(id: string | null) {
    onSelect(id);
  }

  function getLabel(id: string): string {
    return allItems.find((e) => e.id === id)?.label ?? id;
  }
</script>

{#if isMobile}
  <!-- 모바일: 전체화면 모달 -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div
    class="mobile-overlay"
    role="dialog"
    aria-modal="true"
    aria-label="메뉴 선택"
    onkeydown={handleKeydown}
  >
    <!-- backdrop -->
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <div class="mobile-backdrop" onclick={() => onSelect(selectedMenuId)}></div>

    <div class="mobile-modal">
      <!-- 헤더 -->
      <div class="mobile-header">
        <span class="mobile-title">메뉴 선택</span>
        <button
          class="mobile-close"
          aria-label="닫기"
          onclick={() => onSelect(selectedMenuId)}
        ><X size={18} /></button>
      </div>

      <!-- 검색 -->
      <div class="search-wrap">
        <input
          type="text"
          class="search-input"
          placeholder="메뉴 검색..."
          bind:value={searchQuery}
          onkeydown={handleKeydown}
          autocomplete="off"
        />
      </div>

      <!-- 목록 -->
      <ul class="item-list">
        <li
          class="item item--clear"
          class:focused={focusedIndex === 0}
          role="option"
          aria-selected={selectedMenuId === null}
          onclick={() => selectItem(null)}
          onmouseenter={() => (focusedIndex = 0)}
        >
          <span class="item-icon"><X size={14} /></span>
          <span class="item-label">연결 해제</span>
        </li>

        {#each groupedFiltered as group}
          {#if group.category}
            <li class="category-divider">{group.category}</li>
          {/if}
          {#each group.items as item}
            {@const flatIdx = flatList.indexOf(item.id)}
            <li
              class="item"
              class:item--selected={selectedMenuId === item.id}
              class:focused={focusedIndex === flatIdx}
              role="option"
              aria-selected={selectedMenuId === item.id}
              onclick={() => selectItem(item.id)}
              onmouseenter={() => (focusedIndex = flatIdx)}
            >
              <span class="item-icon">{item.icon}</span>
              <span class="item-label">{item.label}</span>
            </li>
          {/each}
        {/each}

        {#if filteredItems.length === 0}
          <li class="empty">검색 결과 없음</li>
        {/if}
      </ul>
    </div>
  </div>
{:else}
  <!-- 데스크톱: 기존 220px 드롭다운 -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div
    class="menu-picker"
    role="listbox"
    aria-label="메뉴 선택"
    tabindex="-1"
    onkeydown={handleKeydown}
  >
    <!-- 검색 -->
    <div class="search-wrap">
      <input
        type="text"
        class="search-input"
        placeholder="메뉴 검색..."
        bind:value={searchQuery}
        onkeydown={handleKeydown}
        autocomplete="off"
      />
    </div>

    <ul class="item-list">
      <!-- 연결 해제 옵션 -->
      <li
        class="item item--clear"
        class:focused={focusedIndex === 0}
        role="option"
        aria-selected={selectedMenuId === null}
        onclick={() => selectItem(null)}
        onmouseenter={() => (focusedIndex = 0)}
      >
        <span class="item-icon"><X size={14} /></span>
        <span class="item-label">연결 해제</span>
      </li>

      <!-- 카테고리 구분 목록 -->
      {#each groupedFiltered as group}
        {#if group.category}
          <li class="category-divider">{group.category}</li>
        {/if}
        {#each group.items as item}
          {@const flatIdx = flatList.indexOf(item.id)}
          <li
            class="item"
            class:item--selected={selectedMenuId === item.id}
            class:focused={focusedIndex === flatIdx}
            role="option"
            aria-selected={selectedMenuId === item.id}
            onclick={() => selectItem(item.id)}
            onmouseenter={() => (focusedIndex = flatIdx)}
          >
            <span class="item-icon">{item.icon}</span>
            <span class="item-label">{item.label}</span>
          </li>
        {/each}
      {/each}

      {#if filteredItems.length === 0}
        <li class="empty">검색 결과 없음</li>
      {/if}
    </ul>
  </div>
{/if}

<style>
  /* ===== 공통 ===== */
  .search-wrap {
    padding: 8px;
    border-bottom: 1px solid var(--border, #313244);
  }

  .search-input {
    width: 100%;
    background: var(--bg-primary, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 4px;
    color: var(--text-primary, #cdd6f4);
    font-size: 12px;
    padding: 4px 8px;
    outline: none;
    box-sizing: border-box;
  }

  .search-input:focus {
    border-color: var(--accent, #89b4fa);
  }

  .item-list {
    list-style: none;
    margin: 0;
    padding: 4px 0;
    overflow-y: auto;
    flex: 1;
  }

  .item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 13px;
    color: var(--text-primary, #cdd6f4);
    border-radius: 4px;
    margin: 0 4px;
  }

  .item:hover,
  .item.focused {
    background: var(--bg-hover, #313244);
  }

  .item--selected {
    color: var(--accent, #89b4fa);
  }

  .item--clear {
    color: var(--text-muted, #6c7086);
    font-size: 12px;
  }

  .item-icon {
    font-size: 14px;
    width: 18px;
    text-align: center;
    flex-shrink: 0;
  }

  .category-divider {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-muted, #6c7086);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 8px 12px 2px;
    list-style: none;
  }

  .empty {
    padding: 12px;
    text-align: center;
    color: var(--text-muted, #6c7086);
    font-size: 12px;
    list-style: none;
  }

  /* ===== 데스크톱 드롭다운 ===== */
  .menu-picker {
    background: var(--bg-secondary, #1e1e2e);
    border: 1px solid var(--border, #313244);
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
    width: 220px;
    max-height: 320px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    outline: none;
  }

  /* ===== 모바일 전체화면 모달 ===== */
  .mobile-overlay {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    align-items: flex-end;
    outline: none;
  }

  .mobile-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
  }

  .mobile-modal {
    position: relative;
    z-index: 1;
    width: 100%;
    max-height: 80vh;
    background: var(--bg-secondary, #1e1e2e);
    border-top: 1px solid var(--border, #313244);
    border-radius: 16px 16px 0 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .mobile-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px 10px;
    border-bottom: 1px solid var(--border, #313244);
  }

  .mobile-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary, #cdd6f4);
  }

  .mobile-close {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-muted, #6c7086);
    font-size: 16px;
    padding: 4px 8px;
    border-radius: 4px;
  }

  .mobile-close:hover {
    background: var(--bg-hover, #313244);
    color: var(--text-primary, #cdd6f4);
  }

  .mobile-modal .search-wrap {
    padding: 10px 12px;
  }

  .mobile-modal .search-input {
    font-size: 14px;
    padding: 8px 10px;
  }

  .mobile-modal .item {
    padding: 10px 16px;
    font-size: 14px;
  }
</style>
