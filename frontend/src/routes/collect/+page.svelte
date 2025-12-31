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

  // 상세보기 모달
  let selectedPost: CollectedPost | null = null;
  let currentImageIndex = 0;

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

  function openDetail(post: CollectedPost) {
    selectedPost = post;
    currentImageIndex = 0;
  }

  function closeDetail() {
    selectedPost = null;
  }

  function formatContent(text: string | null): string {
    if (!text) return '';
    // 줄바꿈을 <br>로 변환하고, @멘션과 #해시태그 스타일링
    const lines = text.split('\n');
    return lines
      .map((line) => {
        return line.replace(/([@#][\w\uAC00-\uD7AF]+)/g, (match) => {
          if (match.startsWith('#')) {
            return `<span class="text-gray-500">${match}</span>`;
          }
          if (match.startsWith('@')) {
            return `<span class="font-semibold text-gray-900">${match}</span>`;
          }
          return match;
        });
      })
      .join('<br/>');
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
    <div class="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 md:gap-4">
      {#each posts as post}
        {@const sourceBadge = getSourceBadge(post.source_type)}
        {@const classificationBadge = getClassificationBadge(post.classification)}
        <div
          class="card hover:shadow-lg transition-shadow cursor-pointer"
          onclick={() => openDetail(post)}
          onkeydown={(e) => e.key === 'Enter' && openDetail(post)}
          role="button"
          tabindex="0"
        >
          <!-- 썸네일 -->
          {#if post.thumbnail}
            <div class="aspect-square bg-gray-100 rounded-lg mb-2 md:mb-3 overflow-hidden relative">
              <img
                src={post.thumbnail}
                alt={post.title || ''}
                class="w-full h-full object-cover"
                loading="lazy"
              />
              <!-- 배지 오버레이 -->
              <div class="absolute top-1 right-1 flex gap-1">
                <span class="px-1.5 py-0.5 text-xs rounded-full {sourceBadge.class} shadow-sm">
                  {sourceBadge.text}
                </span>
                {#if classificationBadge}
                  <span class="px-1.5 py-0.5 text-xs rounded-full {classificationBadge.class} shadow-sm">
                    {classificationBadge.text}
                  </span>
                {/if}
              </div>
            </div>
          {:else}
            <div class="aspect-square bg-gray-200 rounded-lg mb-2 md:mb-3 flex items-center justify-center relative">
              <span class="text-2xl md:text-4xl text-gray-400">
                {post.source_type === 'instagram' ? '📷' : '📄'}
              </span>
              <!-- 배지 오버레이 -->
              <div class="absolute top-1 right-1 flex gap-1">
                <span class="px-1.5 py-0.5 text-xs rounded-full {sourceBadge.class} shadow-sm">
                  {sourceBadge.text}
                </span>
              </div>
            </div>
          {/if}

          <!-- 정보 -->
          <div class="space-y-1">
            <div class="flex items-center justify-between">
              {#if post.account_name}
                <span class="font-medium text-xs md:text-sm text-gray-900 truncate">@{post.account_name}</span>
              {:else}
                <span class="font-medium text-xs md:text-sm text-gray-900 truncate">{post.title || '게시물'}</span>
              {/if}
            </div>
            <p class="text-xs text-gray-500 line-clamp-2 hidden md:block">
              {post.content ? post.content.slice(0, 50) : post.title || ''}
            </p>
            <p class="text-xs text-gray-400">{formatDate(post.created_at)}</p>
          </div>
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

<!-- 상세보기 모달 -->
{#if selectedPost}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4"
    onclick={closeDetail}
    onkeydown={(e) => e.key === 'Escape' && closeDetail()}
    role="dialog"
    tabindex="-1"
  >
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="bg-white rounded-t-xl sm:rounded-xl w-full sm:max-w-lg max-h-[95vh] sm:max-h-[90vh] overflow-auto"
      onclick={(e) => e.stopPropagation()}
    >
      <!-- Header -->
      <div class="sticky top-0 bg-white border-b border-gray-100 px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          {#if selectedPost.account_name}
            <span class="font-semibold text-sm text-gray-900">@{selectedPost.account_name}</span>
          {:else}
            <span class="font-medium text-sm text-gray-700">{selectedPost.title || '게시물'}</span>
          {/if}
          {#if selectedPost.source_type}
            {@const sourceBadge = getSourceBadge(selectedPost.source_type)}
            <span class="px-2 py-0.5 text-xs rounded-full {sourceBadge.class}">{sourceBadge.text}</span>
          {/if}
        </div>
        <button
          onclick={closeDetail}
          class="p-2 hover:bg-gray-100 rounded-full transition-colors"
          aria-label="닫기"
        >
          <svg class="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- 이미지 -->
      {#if selectedPost.thumbnail}
        <div class="relative w-full aspect-square bg-gray-100 overflow-hidden">
          <img
            src={selectedPost.thumbnail}
            alt={selectedPost.title || '게시물 이미지'}
            class="w-full h-full object-cover"
          />
        </div>
      {/if}

      <!-- 본문 -->
      <div class="px-4 py-4">
        <!-- 배지들 -->
        <div class="flex flex-wrap gap-1 mb-3">
          {@const classificationBadge = getClassificationBadge(selectedPost.classification)}
          {@const urlTypeBadge = getUrlTypeBadge(selectedPost.url_type)}
          <span class="px-2 py-0.5 text-xs rounded-full {urlTypeBadge.class}">{urlTypeBadge.text}</span>
          {#if classificationBadge}
            <span class="px-2 py-0.5 text-xs rounded-full {classificationBadge.class}">{classificationBadge.text}</span>
          {/if}
        </div>

        <!-- 제목 -->
        {#if selectedPost.title}
          <h3 class="font-semibold text-gray-900 mb-2">{selectedPost.title}</h3>
        {/if}

        <!-- 내용 -->
        {#if selectedPost.content}
          <div class="text-sm text-gray-700 leading-relaxed mb-4 max-h-60 overflow-y-auto">
            {@html formatContent(selectedPost.content)}
          </div>
        {/if}

        <!-- 태그 -->
        {#if selectedPost.tags && selectedPost.tags.length > 0}
          <div class="flex flex-wrap gap-1 mb-4">
            {#each selectedPost.tags as tag}
              <span class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">{tag}</span>
            {/each}
          </div>
        {/if}

        <!-- 메타 정보 -->
        <div class="text-xs text-gray-400 pt-3 border-t border-gray-100">
          <div class="flex justify-between">
            <span>수집일: {formatDate(selectedPost.created_at)}</span>
            {#if selectedPost.account_name}
              <span>계정: @{selectedPost.account_name}</span>
            {/if}
          </div>
        </div>

        <!-- 액션 버튼 -->
        <div class="flex gap-2 flex-wrap pt-4 mt-4 border-t border-gray-100">
          <a
            href={selectedPost.url}
            target="_blank"
            rel="noopener noreferrer"
            class="btn btn-primary btn-sm"
          >
            원본 보기
          </a>
          <button onclick={closeDetail} class="btn btn-secondary btn-sm">닫기</button>
        </div>
      </div>
    </div>
  </div>
{/if}
