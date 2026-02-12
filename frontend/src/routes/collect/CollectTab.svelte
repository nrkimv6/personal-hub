<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import { page as pageStore } from '$app/stores';
  import { collectApi, type CollectedPost, type CollectedPostFilters } from '$lib/api';
  import type { LLMRequest, UrlParseResponse, ServiceAccountWithProfile } from '$lib/types';
  import { Button } from '$lib/components/ui';

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
  let selectedPostLlmResult: LLMRequest | null = null;
  let loadingLlm = false;

  // 뷰 모드
  type ViewMode = 'grid' | 'list';
  let viewMode: ViewMode = 'grid';
  const STORAGE_KEY_VIEW_MODE = 'collect_view_mode';

  // 선택 모드
  let selectedPostIds: Set<number> = new Set();
  let isSelectMode = false;
  let isBatchProcessing = false;
  let showBatchActionMenu = false;
  let showDeleteConfirmModal = false;

  // URL 수집 모달
  let showUrlCrawlModal = false;
  let urlCrawlInput = '';
  let urlCrawlAccountId: number | null = null;
  let isUrlCrawling = false;
  let isUrlParsing = false;
  let parsedUrl: UrlParseResponse | null = null;
  let accounts: ServiceAccountWithProfile[] = [];

  // 피드 수집 옵션
  let urlCrawlMaxPosts = 20;
  let urlCrawlScrollCount = 3;

  // URL 타입별 스타일
  const urlTypeStyles: Record<string, { icon: string; color: string; bgColor: string }> = {
    single_post: { icon: '📷', color: 'text-primary', bgColor: 'bg-primary-light' },
    single_reel: { icon: '🎬', color: 'text-purple', bgColor: 'bg-purple-light' },
    account_profile: { icon: '👤', color: 'text-success', bgColor: 'bg-success-light' },
    account_reels: { icon: '🎥', color: 'text-pink', bgColor: 'bg-pink-light' },
    hashtag: { icon: '#', color: 'text-warning', bgColor: 'bg-warning-light' },
    reels_explore: { icon: '🔥', color: 'text-error', bgColor: 'bg-error-light' },
    story: { icon: '⏰', color: 'text-foreground', bgColor: 'bg-muted' },
    unknown: { icon: '❓', color: 'text-foreground', bgColor: 'bg-muted' },
  };

  // 피드 타입인지 (추가 옵션 표시용)
  $: isFeedType = parsedUrl && ['account_profile', 'account_reels', 'hashtag', 'reels_explore'].includes(parsedUrl.url_type);

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
        return { class: 'bg-pink-light text-pink', text: 'Instagram' };
      case 'web':
        return { class: 'bg-primary-light text-primary', text: 'Web' };
      default:
        return { class: 'bg-muted text-foreground', text: sourceType };
    }
  }

  function getClassificationBadge(classification: string | null): { class: string; text: string } | null {
    if (!classification) return null;
    switch (classification) {
      case 'event':
        return { class: 'bg-success-light text-success', text: '이벤트' };
      case 'popup':
        return { class: 'bg-purple-light text-purple-800', text: '팝업' };
      case 'uncategorized':
        return { class: 'bg-warning-light text-warning-foreground', text: '미분류' };
      default:
        return { class: 'bg-muted text-foreground', text: classification };
    }
  }

  function getUrlTypeBadge(urlType: string): { class: string; text: string } {
    switch (urlType) {
      case 'instagram_post':
        return { class: 'bg-pink-light text-pink', text: 'IG 게시물' };
      case 'google_form':
        return { class: 'bg-primary-light text-primary', text: 'Google Form' };
      case 'naver_blog':
        return { class: 'bg-success-light text-success', text: '네이버 블로그' };
      case 'naver_form':
        return { class: 'bg-success-light text-success', text: '네이버 폼' };
      default:
        return { class: 'bg-background text-foreground', text: urlType };
    }
  }

  async function openDetail(post: CollectedPost) {
    selectedPost = post;
    currentImageIndex = 0;
    selectedPostLlmResult = null;

    // Instagram 소스인 경우 LLM 결과 조회
    if (post.source_type === 'instagram' && post.source_id) {
      loadingLlm = true;
      try {
        selectedPostLlmResult = await collectApi.getLlmResult(post.source_id);
      } catch (e) {
        console.error('LLM 결과 조회 실패:', e);
      } finally {
        loadingLlm = false;
      }
    }
  }

  function closeDetail() {
    selectedPost = null;
    selectedPostLlmResult = null;
  }

  // ============== 뷰 모드 ==============
  function setViewMode(mode: ViewMode) {
    viewMode = mode;
    if (browser) {
      localStorage.setItem(STORAGE_KEY_VIEW_MODE, mode);
    }
  }

  // ============== 선택 모드 함수 ==============
  function toggleSelectMode() {
    isSelectMode = !isSelectMode;
    if (!isSelectMode) {
      selectedPostIds = new Set();
      showBatchActionMenu = false;
    }
  }

  function togglePostSelection(postId: number, event?: Event) {
    if (event) event.stopPropagation();
    if (selectedPostIds.has(postId)) {
      selectedPostIds.delete(postId);
    } else {
      selectedPostIds.add(postId);
    }
    selectedPostIds = selectedPostIds;  // 반응형 트리거
  }

  function toggleSelectAll() {
    if (selectedPostIds.size === posts.length) {
      selectedPostIds = new Set();
    } else {
      selectedPostIds = new Set(posts.map(p => p.source_id).filter((id): id is number => id !== null));
    }
  }

  async function runBatchAnalysis() {
    if (selectedPostIds.size === 0) return;
    isBatchProcessing = true;
    showBatchActionMenu = false;
    try {
      const result = await collectApi.batchAnalyze([...selectedPostIds]);
      alert(`${result.created_count}개 게시물 AI 분석 요청 완료`);
      toggleSelectMode();
    } catch (e) {
      console.error('일괄 AI 분석 실패:', e);
      alert('AI 분석 요청에 실패했습니다.');
    } finally {
      isBatchProcessing = false;
    }
  }

  async function runBatchDeactivate() {
    if (selectedPostIds.size === 0) return;
    isBatchProcessing = true;
    showBatchActionMenu = false;
    try {
      const result = await collectApi.batchDeactivate([...selectedPostIds]);
      alert(`${result.updated}개 게시물 비활성화 완료`);
      await fetchPosts();
      toggleSelectMode();
    } catch (e) {
      console.error('일괄 비활성화 실패:', e);
      alert('비활성화에 실패했습니다.');
    } finally {
      isBatchProcessing = false;
    }
  }

  function confirmBatchDelete() {
    showBatchActionMenu = false;
    showDeleteConfirmModal = true;
  }

  async function runBatchDelete() {
    if (selectedPostIds.size === 0) return;
    isBatchProcessing = true;
    showDeleteConfirmModal = false;
    try {
      const result = await collectApi.batchDelete([...selectedPostIds]);
      alert(`${result.deleted}개 게시물 삭제 완료`);
      await fetchPosts();
      toggleSelectMode();
    } catch (e) {
      console.error('일괄 삭제 실패:', e);
      alert('삭제에 실패했습니다.');
    } finally {
      isBatchProcessing = false;
    }
  }

  // ============== URL 수집 모달 ==============
  async function fetchAccounts() {
    try {
      accounts = await collectApi.getAccounts();
      if (!urlCrawlAccountId && accounts.length > 0) {
        const defaultAccount = accounts.find(a => a.id === 4);
        urlCrawlAccountId = defaultAccount?.id ?? accounts[0]?.id ?? null;
      }
    } catch (e) {
      console.error('계정 목록 로드 실패:', e);
    }
  }

  function openUrlCrawlModal() {
    showUrlCrawlModal = true;
    urlCrawlInput = '';
    parsedUrl = null;
    urlCrawlMaxPosts = 20;
    urlCrawlScrollCount = 3;
  }

  function closeUrlCrawlModal() {
    showUrlCrawlModal = false;
    urlCrawlInput = '';
    parsedUrl = null;
  }

  let parseTimeout: ReturnType<typeof setTimeout> | null = null;
  async function onUrlInput() {
    if (parseTimeout) clearTimeout(parseTimeout);
    parsedUrl = null;

    const url = urlCrawlInput.trim();
    if (!url || !url.includes('instagram.com')) return;

    parseTimeout = setTimeout(async () => {
      isUrlParsing = true;
      try {
        parsedUrl = await collectApi.parseUrl(url);
      } catch {
        parsedUrl = null;
      } finally {
        isUrlParsing = false;
      }
    }, 300);
  }

  async function submitUrlCrawl() {
    if (!urlCrawlInput.trim()) {
      alert('URL을 입력해주세요.');
      return;
    }
    if (!urlCrawlAccountId) {
      alert('수집에 사용할 계정을 선택해주세요.');
      return;
    }
    if (parsedUrl?.url_type === 'story') {
      alert('스토리 크롤링은 지원되지 않습니다.');
      return;
    }

    isUrlCrawling = true;
    try {
      if (isFeedType) {
        await collectApi.crawlByGenericUrl(urlCrawlInput.trim(), urlCrawlAccountId, {
          maxPosts: urlCrawlMaxPosts,
          scrollCount: urlCrawlScrollCount
        });
      } else {
        await collectApi.crawlByGenericUrl(urlCrawlInput.trim(), urlCrawlAccountId);
      }
      alert('수집 요청이 등록되었습니다. 워커가 처리하면 게시물이 추가됩니다.');
      closeUrlCrawlModal();
    } catch (e) {
      alert('수집 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    } finally {
      isUrlCrawling = false;
    }
  }

  // ============== 상세보기 액션 ==============
  async function deletePost(id: number) {
    if (!confirm('이 게시물을 삭제하시겠습니까?')) return;
    try {
      await collectApi.deletePost(id);
      closeDetail();
      await fetchPosts();
    } catch (e) {
      alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function recrawlPost(id: number) {
    try {
      await collectApi.recrawlPost(id);
      alert('재크롤링 요청이 등록되었습니다. 워커가 처리하면 게시물 정보가 업데이트됩니다.');
    } catch (e) {
      alert('재크롤링 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  async function requestLlmAnalysis(id: number) {
    try {
      await collectApi.requestLlmAnalysisSingle(id);
      alert('AI 분석 요청이 등록되었습니다.');
    } catch (e) {
      alert('AI 분석 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  function formatContent(text: string | null): string {
    if (!text) return '';
    // 줄바꿈을 <br>로 변환하고, @멘션과 #해시태그 스타일링
    const lines = text.split('\n');
    return lines
      .map((line) => {
        return line.replace(/([@#][\w\uAC00-\uD7AF]+)/g, (match) => {
          if (match.startsWith('#')) {
            return `<span class="text-muted-foreground">${match}</span>`;
          }
          if (match.startsWith('@')) {
            return `<span class="font-semibold text-foreground">${match}</span>`;
          }
          return match;
        });
      })
      .join('<br/>');
  }

  onMount(() => {
    // 저장된 뷰 모드 복원
    if (browser) {
      const savedMode = localStorage.getItem(STORAGE_KEY_VIEW_MODE);
      if (savedMode === 'grid' || savedMode === 'list') {
        viewMode = savedMode;
      }
    }

    // PWA Share Target에서 전달된 URL 처리
    const sharedUrl = $pageStore.url.searchParams.get('shared_url');
    if (sharedUrl) {
      showUrlCrawlModal = true;
      urlCrawlInput = sharedUrl;
      onUrlInput();
      if (browser) {
        const newUrl = new URL(window.location.href);
        newUrl.searchParams.delete('shared_url');
        window.history.replaceState(null, '', newUrl.pathname + newUrl.search);
      }
    }

    fetchAccounts();
    fetchPosts();
    fetchUrlTypes();
  });
</script>

<div class="space-y-4 mt-2">
  <!-- 필터 -->
  <div class="card">
    <div class="flex flex-wrap gap-4 items-end">
      <!-- 소스 타입 -->
      <div>
        <label for="sourceType" class="block text-sm font-medium text-foreground mb-1">소스</label>
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
        <label for="urlType" class="block text-sm font-medium text-foreground mb-1">URL 타입</label>
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
        <label for="classification" class="block text-sm font-medium text-foreground mb-1">분류</label>
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
        <label for="search" class="block text-sm font-medium text-foreground mb-1">검색</label>
        <div class="flex gap-2">
          <input
            id="search"
            type="text"
            bind:value={search}
            placeholder="제목, 본문, URL 검색..."
            class="input input-sm flex-1"
            onkeydown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <Button on:click={handleSearch} variant="primary" size="sm">검색</Button>
        </div>
      </div>
    </div>
  </div>

  <!-- 툴바 -->
  <div class="flex justify-between items-center">
    <!-- 왼쪽: 통계 + 선택 모드 -->
    <div class="flex items-center gap-4">
      <span class="text-sm text-muted-foreground">총 {total}개</span>
      {#if isSelectMode}
        <span class="text-sm text-primary font-medium">{selectedPostIds.size}개 선택됨</span>
        <Button on:click={toggleSelectAll} variant="secondary" size="xs">
          {selectedPostIds.size === posts.length ? '전체 해제' : '전체 선택'}
        </Button>
      {/if}
    </div>

    <!-- 오른쪽: 액션 버튼들 -->
    <div class="flex items-center gap-2">
      <!-- 일괄 작업 메뉴 (선택 모드에서만) -->
      {#if isSelectMode && selectedPostIds.size > 0}
        <div class="relative">
          <Button
            on:click={() => showBatchActionMenu = !showBatchActionMenu}
            variant="primary"
            size="sm"
            disabled={isBatchProcessing}
          >
            {isBatchProcessing ? '처리 중...' : '일괄 작업'}
          </Button>
          {#if showBatchActionMenu}
            <div class="absolute right-0 mt-1 w-40 bg-white rounded-lg shadow-lg border border-border z-10">
              <button
                onclick={runBatchAnalysis}
                class="w-full px-4 py-2 text-left text-sm hover:bg-muted"
              >
                AI 분석 요청
              </button>
              <button
                onclick={runBatchDeactivate}
                class="w-full px-4 py-2 text-left text-sm hover:bg-muted"
              >
                비활성화
              </button>
              <button
                onclick={confirmBatchDelete}
                class="w-full px-4 py-2 text-left text-sm text-error hover:bg-error-light"
              >
                삭제
              </button>
            </div>
          {/if}
        </div>
      {/if}

      <!-- 선택 모드 토글 -->
      <Button
        on:click={toggleSelectMode}
        variant={isSelectMode ? 'primary' : 'secondary'}
        size="sm"
      >
        {isSelectMode ? '선택 취소' : '선택'}
      </Button>

      <!-- URL 수집 버튼 -->
      <Button on:click={openUrlCrawlModal} variant="secondary" size="sm">
        URL 수집
      </Button>

      <!-- 뷰 모드 토글 -->
      <div class="flex border border-border rounded-lg overflow-hidden">
        <button
          onclick={() => setViewMode('grid')}
          class="px-3 py-1.5 text-sm {viewMode === 'grid' ? 'bg-primary text-white' : 'bg-white text-muted-foreground hover:bg-muted'}"
          title="그리드 뷰"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
          </svg>
        </button>
        <button
          onclick={() => setViewMode('list')}
          class="px-3 py-1.5 text-sm {viewMode === 'list' ? 'bg-primary text-white' : 'bg-white text-muted-foreground hover:bg-muted'}"
          title="리스트 뷰"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>

      <span class="text-sm text-muted-foreground">{page} / {totalPages} 페이지</span>
    </div>
  </div>

  <!-- 게시물 목록 -->
  {#if loading}
    <div class="flex justify-center items-center h-64">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  {:else if error}
    <div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
      {error}
    </div>
  {:else if posts.length === 0}
    <div class="card text-center py-12">
      <p class="text-muted-foreground">게시물이 없습니다</p>
    </div>
  {:else}
    <!-- 그리드 뷰 -->
    {#if viewMode === 'grid'}
      <div class="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 md:gap-4">
        {#each posts as post}
          {@const sourceBadge = getSourceBadge(post.source_type)}
          {@const classificationBadge = getClassificationBadge(post.classification)}
          <div
            class="card hover:shadow-lg transition-shadow cursor-pointer relative {isSelectMode && post.source_id && selectedPostIds.has(post.source_id) ? 'ring-2 ring-blue-500' : ''}"
            onclick={() => isSelectMode && post.source_id ? togglePostSelection(post.source_id) : openDetail(post)}
            onkeydown={(e) => e.key === 'Enter' && (isSelectMode && post.source_id ? togglePostSelection(post.source_id) : openDetail(post))}
            role="button"
            tabindex="0"
          >
            <!-- 선택 체크박스 (선택 모드에서만) -->
            {#if isSelectMode && post.source_id}
              <div class="absolute top-2 left-2 z-10">
                <input
                  type="checkbox"
                  checked={selectedPostIds.has(post.source_id)}
                  onclick={(e) => { e.stopPropagation(); togglePostSelection(post.source_id!); }}
                  class="w-5 h-5 rounded border-border text-primary focus:ring-ring"
                />
              </div>
            {/if}

            <!-- 썸네일 -->
            {#if post.thumbnail}
              <div class="aspect-square bg-muted rounded-lg mb-2 md:mb-3 overflow-hidden relative">
                <img
                  src={post.thumbnail}
                  alt={post.title || ''}
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
                <!-- 배지 오버레이 -->
                <div class="absolute top-1 right-1 flex gap-1">
                  {#if post.llm_status}
                    {#if post.llm_status === 'completed'}
                      <span class="px-1.5 py-0.5 text-xs bg-success text-white rounded-full shadow-sm" title="AI 분석 완료">AI</span>
                    {:else if post.llm_status === 'pending' || post.llm_status === 'processing'}
                      <span class="px-1.5 py-0.5 text-xs bg-warning text-white rounded-full shadow-sm animate-pulse" title="AI 분석 대기중">AI</span>
                    {:else if post.llm_status === 'failed'}
                      <span class="px-1.5 py-0.5 text-xs bg-error text-white rounded-full shadow-sm" title="AI 분석 실패">AI</span>
                    {/if}
                  {/if}
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
              <div class="aspect-square bg-secondary rounded-lg mb-2 md:mb-3 flex items-center justify-center relative">
                <span class="text-2xl md:text-4xl text-muted-foreground">
                  {post.source_type === 'instagram' ? '📷' : '📄'}
                </span>
                <!-- 배지 오버레이 -->
                <div class="absolute top-1 right-1 flex gap-1">
                  {#if post.llm_status}
                    {#if post.llm_status === 'completed'}
                      <span class="px-1.5 py-0.5 text-xs bg-success text-white rounded-full shadow-sm" title="AI 분석 완료">AI</span>
                    {:else if post.llm_status === 'pending' || post.llm_status === 'processing'}
                      <span class="px-1.5 py-0.5 text-xs bg-warning text-white rounded-full shadow-sm animate-pulse" title="AI 분석 대기중">AI</span>
                    {:else if post.llm_status === 'failed'}
                      <span class="px-1.5 py-0.5 text-xs bg-error text-white rounded-full shadow-sm" title="AI 분석 실패">AI</span>
                    {/if}
                  {/if}
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
                  <span class="font-medium text-xs md:text-sm text-foreground truncate">@{post.account_name}</span>
                {:else}
                  <span class="font-medium text-xs md:text-sm text-foreground truncate">{post.title || '게시물'}</span>
                {/if}
              </div>
              <p class="text-xs text-muted-foreground line-clamp-2 hidden md:block">
                {post.content ? post.content.slice(0, 50) : post.title || ''}
              </p>
              <p class="text-xs text-muted-foreground">{formatDate(post.created_at)}</p>
            </div>
          </div>
        {/each}
      </div>
    {:else}
      <!-- 리스트 뷰 -->
      <div class="space-y-2">
        {#each posts as post}
          {@const sourceBadge = getSourceBadge(post.source_type)}
          {@const classificationBadge = getClassificationBadge(post.classification)}
          <div
            class="card flex items-center gap-4 p-3 hover:shadow-md transition-shadow cursor-pointer {isSelectMode && post.source_id && selectedPostIds.has(post.source_id) ? 'ring-2 ring-blue-500' : ''}"
            onclick={() => isSelectMode && post.source_id ? togglePostSelection(post.source_id) : openDetail(post)}
            onkeydown={(e) => e.key === 'Enter' && (isSelectMode && post.source_id ? togglePostSelection(post.source_id) : openDetail(post))}
            role="button"
            tabindex="0"
          >
            <!-- 선택 체크박스 (선택 모드에서만) -->
            {#if isSelectMode && post.source_id}
              <input
                type="checkbox"
                checked={selectedPostIds.has(post.source_id)}
                onclick={(e) => { e.stopPropagation(); togglePostSelection(post.source_id!); }}
                class="w-5 h-5 rounded border-border text-primary focus:ring-ring"
              />
            {/if}

            <!-- 썸네일 -->
            <div class="w-16 h-16 flex-shrink-0 rounded-lg overflow-hidden bg-muted">
              {#if post.thumbnail}
                <img
                  src={post.thumbnail}
                  alt={post.title || ''}
                  class="w-full h-full object-cover"
                  loading="lazy"
                />
              {:else}
                <div class="w-full h-full flex items-center justify-center text-2xl text-muted-foreground">
                  {post.source_type === 'instagram' ? '📷' : '📄'}
                </div>
              {/if}
            </div>

            <!-- 정보 -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                {#if post.account_name}
                  <span class="font-medium text-sm text-foreground">@{post.account_name}</span>
                {:else}
                  <span class="font-medium text-sm text-foreground truncate">{post.title || '게시물'}</span>
                {/if}
                {#if post.llm_status}
                  {#if post.llm_status === 'completed'}
                    <span class="px-1.5 py-0.5 text-xs bg-success-light text-success rounded" title="AI 분석 완료">AI</span>
                  {:else if post.llm_status === 'pending' || post.llm_status === 'processing'}
                    <span class="px-1.5 py-0.5 text-xs bg-warning-light text-warning-foreground rounded animate-pulse" title="AI 분석 대기중">AI</span>
                  {:else if post.llm_status === 'failed'}
                    <span class="px-1.5 py-0.5 text-xs bg-error-light text-error rounded" title="AI 분석 실패">AI</span>
                  {/if}
                {/if}
                <span class="px-1.5 py-0.5 text-xs rounded-full {sourceBadge.class}">
                  {sourceBadge.text}
                </span>
                {#if classificationBadge}
                  <span class="px-1.5 py-0.5 text-xs rounded-full {classificationBadge.class}">
                    {classificationBadge.text}
                  </span>
                {/if}
              </div>
              <p class="text-sm text-muted-foreground line-clamp-1">
                {post.content ? post.content.slice(0, 100) : post.title || ''}
              </p>
              <p class="text-xs text-muted-foreground mt-1">{formatDate(post.created_at)}</p>
            </div>
          </div>
        {/each}
      </div>
    {/if}

    <!-- 페이지네이션 -->
    {#if totalPages > 1}
      <div class="flex justify-center items-center gap-4 mt-6">
        <Button
          on:click={prevPage}
          disabled={!canPrevPage}
          variant="secondary"
          size="sm"
        >
          이전
        </Button>
        <span class="text-sm text-muted-foreground">
          {page} / {totalPages}
        </span>
        <Button
          on:click={nextPage}
          disabled={!canNextPage}
          variant="secondary"
          size="sm"
        >
          다음
        </Button>
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
      <div class="sticky top-0 bg-card border-b border-border px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          {#if selectedPost.account_name}
            <span class="font-semibold text-sm text-foreground">@{selectedPost.account_name}</span>
          {:else}
            <span class="font-medium text-sm text-foreground">{selectedPost.title || '게시물'}</span>
          {/if}
          {#if selectedPost.source_type}
            {@const sourceBadge = getSourceBadge(selectedPost.source_type)}
            <span class="px-2 py-0.5 text-xs rounded-full {sourceBadge.class}">{sourceBadge.text}</span>
          {/if}
        </div>
        <button
          onclick={closeDetail}
          class="p-2 hover:bg-muted rounded-full transition-colors"
          aria-label="닫기"
        >
          <svg class="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- 이미지 -->
      {#if selectedPost.thumbnail}
        <div class="relative w-full aspect-square bg-muted overflow-hidden">
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
        {#if selectedPost}
          {@const classificationBadge = getClassificationBadge(selectedPost.classification)}
          {@const urlTypeBadge = getUrlTypeBadge(selectedPost.url_type)}
          <div class="flex flex-wrap gap-1 mb-3">
            <span class="px-2 py-0.5 text-xs rounded-full {urlTypeBadge.class}">{urlTypeBadge.text}</span>
            {#if classificationBadge}
              <span class="px-2 py-0.5 text-xs rounded-full {classificationBadge.class}">{classificationBadge.text}</span>
            {/if}
          </div>
        {/if}

        <!-- 제목 -->
        {#if selectedPost.title}
          <h3 class="font-semibold text-foreground mb-2">{selectedPost.title}</h3>
        {/if}

        <!-- 내용 -->
        {#if selectedPost.content}
          <div class="text-sm text-foreground leading-relaxed mb-4 max-h-60 overflow-y-auto">
            {@html formatContent(selectedPost.content)}
          </div>
        {/if}

        <!-- 태그 -->
        {#if selectedPost.tags && selectedPost.tags.length > 0}
          <div class="flex flex-wrap gap-1 mb-4">
            {#each selectedPost.tags as tag}
              <span class="px-2 py-0.5 text-xs bg-muted text-muted-foreground rounded-full">{tag}</span>
            {/each}
          </div>
        {/if}

        <!-- 메타 정보 -->
        <div class="text-xs text-muted-foreground pt-3 border-t border-border">
          <div class="flex justify-between">
            <span>수집일: {formatDate(selectedPost.created_at)}</span>
            {#if selectedPost.account_name}
              <span>계정: @{selectedPost.account_name}</span>
            {/if}
          </div>
        </div>

        <!-- AI 분석 결과 (Instagram 전용) -->
        {#if selectedPost.source_type === 'instagram' && selectedPost.source_id}
          <div class="pt-3 border-t border-border mb-4">
            <h4 class="text-sm font-medium text-foreground mb-2">AI 분석</h4>
            {#if loadingLlm}
              <div class="text-sm text-muted-foreground">로딩 중...</div>
            {:else if selectedPostLlmResult?.result}
              <div class="bg-background rounded-lg p-3 text-sm">
                <div class="flex items-center gap-2 mb-2">
                  <span class="font-medium">분류:</span>
                  <span class="px-2 py-0.5 rounded-full text-xs {selectedPostLlmResult.result.tag === '이벤트' ? 'bg-success-light text-success' : selectedPostLlmResult.result.tag === '팝업' ? 'bg-purple-light text-purple' : 'bg-muted text-foreground'}">
                    {selectedPostLlmResult.result.tag || '미분류'}
                  </span>
                </div>
                {#if selectedPostLlmResult.result.summary}
                  <p class="text-muted-foreground">{selectedPostLlmResult.result.summary}</p>
                {/if}
              </div>
            {:else if selectedPostLlmResult}
              <div class="text-sm text-muted-foreground">상태: {selectedPostLlmResult.status}</div>
            {:else}
              <div class="text-sm text-muted-foreground">분석 결과 없음</div>
            {/if}
          </div>
        {/if}

        <!-- 액션 버튼 -->
        <div class="flex gap-2 flex-wrap pt-4 mt-4 border-t border-border">
          <a
            href={selectedPost.url}
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-active h-9 px-3 text-sm rounded-md"
          >
            원본 보기
          </a>
          {#if selectedPost.source_type === 'instagram' && selectedPost.source_id}
            {@const postSourceId = selectedPost.source_id}
            <Button on:click={() => recrawlPost(postSourceId)} variant="secondary" size="sm">
              재크롤링
            </Button>
            <Button on:click={() => requestLlmAnalysis(postSourceId)} variant="secondary" size="sm">
              AI 분석
            </Button>
            <Button on:click={() => deletePost(postSourceId)} variant="destructive" size="sm">
              삭제
            </Button>
          {/if}
          <Button on:click={closeDetail} variant="secondary" size="sm">닫기</Button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- URL 수집 모달 -->
{#if showUrlCrawlModal}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
    onclick={closeUrlCrawlModal}
    onkeydown={(e) => e.key === 'Escape' && closeUrlCrawlModal()}
  >
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="bg-white rounded-xl w-full max-w-md p-6"
      onclick={(e) => e.stopPropagation()}
    >
      <h3 class="text-lg font-semibold mb-4">Instagram URL 수집</h3>

      <!-- URL 입력 -->
      <div class="mb-4">
        <label for="urlCrawlInput" class="block text-sm font-medium text-foreground mb-1">
          Instagram URL
        </label>
        <input
          id="urlCrawlInput"
          type="text"
          bind:value={urlCrawlInput}
          oninput={onUrlInput}
          placeholder="https://www.instagram.com/..."
          class="input w-full"
        />
      </div>

      <!-- URL 파싱 결과 -->
      {#if isUrlParsing}
        <div class="text-sm text-muted-foreground mb-4">URL 분석 중...</div>
      {:else if parsedUrl}
        {@const style = urlTypeStyles[parsedUrl.url_type] || urlTypeStyles.unknown}
        <div class="mb-4 p-3 rounded-lg {style.bgColor}">
          <div class="flex items-center gap-2">
            <span class="text-xl">{style.icon}</span>
            <div>
              <span class="font-medium {style.color}">{parsedUrl.url_type_description}</span>
              {#if parsedUrl.username}
                <span class="text-sm text-muted-foreground ml-2">@{parsedUrl.username}</span>
              {/if}
              {#if parsedUrl.hashtag}
                <span class="text-sm text-muted-foreground ml-2">#{parsedUrl.hashtag}</span>
              {/if}
            </div>
          </div>
          {#if !parsedUrl.is_supported}
            <p class="text-sm text-error mt-2">이 URL 타입은 지원되지 않습니다.</p>
          {/if}
        </div>
      {/if}

      <!-- 피드 타입 옵션 -->
      {#if isFeedType}
        <div class="mb-4 space-y-3">
          <div>
            <label for="maxPosts" class="block text-sm font-medium text-foreground mb-1">
              최대 게시물 수
            </label>
            <input
              id="maxPosts"
              type="number"
              bind:value={urlCrawlMaxPosts}
              min="1"
              max="100"
              class="input w-full"
            />
          </div>
          <div>
            <label for="scrollCount" class="block text-sm font-medium text-foreground mb-1">
              스크롤 횟수
            </label>
            <input
              id="scrollCount"
              type="number"
              bind:value={urlCrawlScrollCount}
              min="1"
              max="20"
              class="input w-full"
            />
          </div>
        </div>
      {/if}

      <!-- 계정 선택 -->
      <div class="mb-4">
        <label for="urlCrawlAccount" class="block text-sm font-medium text-foreground mb-1">
          수집 계정
        </label>
        <select
          id="urlCrawlAccount"
          bind:value={urlCrawlAccountId}
          class="input w-full"
        >
          {#each accounts as account}
            <option value={account.id}>{account.identifier || account.profile_name || `계정 ${account.id}`}</option>
          {/each}
        </select>
      </div>

      <!-- 버튼 -->
      <div class="flex gap-2 justify-end">
        <Button on:click={closeUrlCrawlModal} variant="secondary">취소</Button>
        <Button
          on:click={submitUrlCrawl}
          disabled={isUrlCrawling || !urlCrawlInput.trim() || !urlCrawlAccountId || (parsedUrl && !parsedUrl.is_supported)}
          variant="primary"
        >
          {isUrlCrawling ? '요청 중...' : '수집 요청'}
        </Button>
      </div>
    </div>
  </div>
{/if}

<!-- 삭제 확인 모달 -->
{#if showDeleteConfirmModal}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
    onclick={() => showDeleteConfirmModal = false}
  >
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="bg-white rounded-xl w-full max-w-sm p-6"
      onclick={(e) => e.stopPropagation()}
    >
      <h3 class="text-lg font-semibold mb-4">삭제 확인</h3>
      <p class="text-muted-foreground mb-6">
        선택한 {selectedPostIds.size}개 게시물을 삭제하시겠습니까?<br/>
        이 작업은 되돌릴 수 없습니다.
      </p>
      <div class="flex gap-2 justify-end">
        <Button on:click={() => showDeleteConfirmModal = false} variant="secondary">취소</Button>
        <Button on:click={runBatchDelete} variant="destructive">삭제</Button>
      </div>
    </div>
  </div>
{/if}
