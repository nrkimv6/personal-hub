<script lang="ts">
  import { navEntries, groupEntriesByCategory, isNavGroup, type NavSingleItem } from '$lib/navigation';

  export let selectedMenuId: string | null = null;
  export let onSelect: (menuId: string | null) => void = () => {};

  let searchQuery = '';
  let focusedIndex = -1;

  // 단일 아이템만 필터 (NavGroup 제외)
  const singleItems: NavSingleItem[] = navEntries.filter(
    (e): e is NavSingleItem => !isNavGroup(e)
  );

  $: filteredItems = searchQuery.trim()
    ? singleItems.filter((e) =>
        e.label.toLowerCase().includes(searchQuery.trim().toLowerCase())
      )
    : singleItems;

  $: groupedFiltered = groupEntriesByCategory(filteredItems);

  // 플랫 목록 (키보드 탐색용)
  $: flatList = ['__clear__', ...filteredItems.map((e) => e.id)];

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
    return singleItems.find((e) => e.id === id)?.label ?? id;
  }
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
<div
  class="menu-picker"
  role="listbox"
  aria-label="메뉴 선택"
  tabindex="-1"
  on:keydown={handleKeydown}
>
  <!-- 검색 -->
  <div class="search-wrap">
    <input
      type="text"
      class="search-input"
      placeholder="메뉴 검색..."
      bind:value={searchQuery}
      on:keydown={handleKeydown}
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
      on:click={() => selectItem(null)}
      on:mouseenter={() => (focusedIndex = 0)}
    >
      <span class="item-icon">✕</span>
      <span class="item-label">연결 해제</span>
    </li>

    <!-- 카테고리 구분 목록 -->
    {#each groupedFiltered as group}
      {#if group.category}
        <li class="category-divider">{group.category}</li>
      {/if}
      {#each group.entries as entry}
        {@const item = entry as NavSingleItem}
        {@const flatIdx = flatList.indexOf(item.id)}
        <li
          class="item"
          class:item--selected={selectedMenuId === item.id}
          class:focused={focusedIndex === flatIdx}
          role="option"
          aria-selected={selectedMenuId === item.id}
          on:click={() => selectItem(item.id)}
          on:mouseenter={() => (focusedIndex = flatIdx)}
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

<style>
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
</style>
