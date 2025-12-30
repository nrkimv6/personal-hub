<script lang="ts">
  import { onMount } from 'svelte';
  import { collectApi, type CollectedPost, type CollectedPostFilters } from '$lib/api';

  let posts: CollectedPost[] = [];
  let loading = true;
  let error: string | null = null;

  // 페이지네이션
  let page = 1;
  let limit = 20;
  let total = 0;
  let totalPages = 0;

  // 필터
  let sourceType: string = '';
  let urlType: string = '';
  let classification: string = '';
  let search: string = '';

  // URL 타입 목록
  let urlTypes: string[] = [];

  $: canPrevPage = page > 1;
  $: canNextPage = page < totalPages;

  async function fetchPosts() {
    loading = true;
    error = null;
    try {
      const params: CollectedPostFilters = {
        page,
        limit,
      };
      if (sourceType) params.source_type = sourceType;
      if (urlType) params.url_type = urlType;
      if (classification) params.classification = classification;
      if (search) params.search = search;

      const result = await collectApi.getPosts(params);
      posts = result.items;
      total = result.total;
      totalPages = result.total_pages;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  async function fetchUrlTypes() {
    try {
      urlTypes = await collectApi.getUrlTypes();
    } catch (e) {
      console.error('URL 타입 로드 실패:', e);
    }
  }

  function handleFilterChange() {
    page = 1;
    fetchPosts();
  }

  function handleSearch() {
    page = 1;
    fetchPosts();
  }

  function prevPage() {
    if (canPrevPage) {
      page--;
      fetchPosts();
    }
  }

  function nextPage() {
    if (canNextPage) {
      page++;
      fetchPosts();
    }
  }

  function formatDate(dateString: string): string {
    const date = new Date(dateString);
    return date.toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function getSourceBadge(sourceType: string): { class: string; text: string } {
    switch (sourceType) {
      case 'instagram':
        return { class: 'bg-pink-100 text-pink-800', text: 'Instagram' };
      case 'web':
        return { class: 'bg-blue-100 text-blue-800', text: 'Web' };
      default:
        return { class: 'bg-gray-100 text-gray-800', text: sourceType };
    }
  }

  function getClassificationBadge(classification: string | null): { class: string; text: string } | null {
    if (!classification) return null;
    switch (classification) {
      case 'event':
        return { class: 'bg-green-100 text-green-800', text: '이벤트' };
      case 'popup':
        return { class: 'bg-purple-100 text-purple-800', text: '팝업' };
      case 'uncategorized':
        return { class: 'bg-yellow-100 text-yellow-800', text: '미분류' };
      default:
        return { class: 'bg-gray-100 text-gray-800', text: classification };
    }
  }

  function getUrlTypeBadge(urlType: string): { class: string; text: string } {
    switch (urlType) {
      case 'instagram_post':
        return { class: 'bg-pink-50 text-pink-700', text: 'IG 게시물' };
      case 'google_form':
        return { class: 'bg-blue-50 text-blue-700', text: 'Google Form' };
      case 'naver_blog':
        return { class: 'bg-green-50 text-green-700', text: '네이버 블로그' };
      case 'naver_form':
        return { class: 'bg-green-50 text-green-700', text: '네이버 폼' };
      default:
        return { class: 'bg-gray-50 text-gray-700', text: urlType };
    }
  }

  onMount(() => {
    fetchPosts();
    fetchUrlTypes();
  });
</script>

<div class="space-y-4">
  <!-- 필터 -->
  <div class="card">
    <div class="flex flex-wrap gap-4 items-end">
      <!-- 소스 타입 -->
      <div>
        <label for="sourceType" class="block text-sm font-medium text-gray-700 mb-1">소스</label>
        <select
          id="sourceType"
          bind:value={sourceType}
          onchange={handleFilterChange}
          class="input input-sm w-32"
        >
          <option value="">전체</option>
          <option value="instagram">Instagram</option>
          <option value="web">Web</option>
        </select>
      </div>

      <!-- URL 타입 -->
      <div>
        <label for="urlType" class="block text-sm font-medium text-gray-700 mb-1">URL 타입</label>
        <select
          id="urlType"
          bind:value={urlType}
          onchange={handleFilterChange}
          class="input input-sm w-40"
        >
          <option value="">전체</option>
          {#each urlTypes as type}
            <option value={type}>{type}</option>
          {/each}
        </select>
      </div>

      <!-- 분류 상태 -->
      <div>
        <label for="classification" class="block text-sm font-medium text-gray-700 mb-1">분류</label>
        <select
          id="classification"
          bind:value={classification}
          onchange={handleFilterChange}
          class="input input-sm w-32"
        >
          <option value="">전체</option>
          <option value="event">이벤트</option>
          <option value="popup">팝업</option>
          <option value="uncategorized">미분류</option>
          <option value="unclassified">분류 전</option>
        </select>
      </div>

      <!-- 검색 -->
      <div class="flex-1 min-w-[200px]">
        <label for="search" class="block text-sm font-medium text-gray-700 mb-1">검색</label>
        <div class="flex gap-2">
          <input
            id="search"
            type="text"
            bind:value={search}
            placeholder="제목, 본문, URL 검색..."
            class="input input-sm flex-1"
            onkeydown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <button onclick={handleSearch} class="btn btn-primary btn-sm">검색</button>
        </div>
      </div>
    </div>
  </div>

  <!-- 통계 -->
  <div class="flex justify-between items-center text-sm text-gray-600">
    <span>총 {total}개</span>
    <span>{page} / {totalPages} 페이지</span>
  </div>

  <!-- 게시물 목록 -->
  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else if posts.length === 0}
    <div class="card text-center py-12">
      <p class="text-gray-500">게시물이 없습니다</p>
    </div>
  {:else}
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {#each posts as post}
        {@const sourceBadge = getSourceBadge(post.source_type)}
        {@const classificationBadge = getClassificationBadge(post.classification)}
        {@const urlTypeBadge = getUrlTypeBadge(post.url_type)}
        <div class="card hover:shadow-lg transition-shadow">
          <!-- 썸네일 -->
          {#if post.thumbnail}
            <div class="aspect-square bg-gray-100 rounded-lg overflow-hidden mb-3">
              <img
                src={post.thumbnail}
                alt={post.title || ''}
                class="w-full h-full object-cover"
                loading="lazy"
              />
            </div>
          {:else}
            <div class="aspect-square bg-gray-100 rounded-lg flex items-center justify-center mb-3">
              <span class="text-4xl text-gray-400">
                {post.source_type === 'instagram' ? '📷' : '📄'}
              </span>
            </div>
          {/if}

          <!-- 배지들 -->
          <div class="flex flex-wrap gap-1 mb-2">
            <span class="px-2 py-0.5 text-xs rounded-full {sourceBadge.class}">
              {sourceBadge.text}
            </span>
            <span class="px-2 py-0.5 text-xs rounded-full {urlTypeBadge.class}">
              {urlTypeBadge.text}
            </span>
            {#if classificationBadge}
              <span class="px-2 py-0.5 text-xs rounded-full {classificationBadge.class}">
                {classificationBadge.text}
              </span>
            {/if}
          </div>

          <!-- 제목/본문 -->
          <h3 class="font-medium text-gray-900 line-clamp-2 mb-1">
            {post.title || '(제목 없음)'}
          </h3>

          <!-- 메타 정보 -->
          <div class="text-xs text-gray-500 space-y-1">
            {#if post.account_name}
              <p>@{post.account_name}</p>
            {/if}
            <p>{formatDate(post.created_at)}</p>
          </div>

          <!-- 태그 -->
          {#if post.tags && post.tags.length > 0}
            <div class="flex flex-wrap gap-1 mt-2">
              {#each post.tags.slice(0, 3) as tag}
                <span class="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600 rounded">
                  {tag}
                </span>
              {/each}
              {#if post.tags.length > 3}
                <span class="px-1.5 py-0.5 text-xs text-gray-400">
                  +{post.tags.length - 3}
                </span>
              {/if}
            </div>
          {/if}

          <!-- 링크 -->
          <a
            href={post.url}
            target="_blank"
            rel="noopener noreferrer"
            class="mt-3 text-xs text-blue-600 hover:underline truncate block"
          >
            원본 보기 →
          </a>
        </div>
      {/each}
    </div>

    <!-- 페이지네이션 -->
    {#if totalPages > 1}
      <div class="flex justify-center items-center gap-4 mt-6">
        <button
          onclick={prevPage}
          disabled={!canPrevPage}
          class="btn btn-secondary btn-sm"
        >
          이전
        </button>
        <span class="text-sm text-gray-600">
          {page} / {totalPages}
        </span>
        <button
          onclick={nextPage}
          disabled={!canNextPage}
          class="btn btn-secondary btn-sm"
        >
          다음
        </button>
      </div>
    {/if}
  {/if}
</div>
