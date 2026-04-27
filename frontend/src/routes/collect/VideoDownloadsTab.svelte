<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { videoDownloadApi } from '$lib/api';
  import type { VideoDownload, VideoDownloadStats, VideoDownloadType, VideoDownloadStatus } from '$lib/types';

  let downloads: VideoDownload[] = [];
  let stats: VideoDownloadStats | null = null;
  let loading = true;
  let error: string | null = null;

  // 페이지네이션
  let page = 1;
  let pageSize = 20;
  let total = 0;
  let totalPages = 0;

  // 필터
  let statusFilter: string = '';
  let typeFilter: string = '';

  // 새 다운로드 폼
  let showAddModal = false;
  let newUrl = '';
  let newType: VideoDownloadType | '' = '';
  let newQuality = 'best';
  let newEmbeddingUrl = '';
  let newOutputFilename = '';
  let isSubmitting = false;

  // 배치 모드
  let batchMode = false;
  let batchUrls: string[] = [''];
  let batchOutputPrefix = '';

  // 자동 새로고침
  let refreshInterval: ReturnType<typeof setInterval> | null = null;
  let autoRefresh = true;

  $: canPrevPage = page > 1;
  $: canNextPage = page < totalPages;

  // 타입별 스타일
  const typeStyles: Record<VideoDownloadType, { label: string; color: string }> = {
    youtube: { label: 'YouTube', color: 'text-error bg-error-light' },
    youtube_stream: { label: 'YouTube Live', color: 'text-error bg-red-200' },
    vimeo: { label: 'Vimeo', color: 'text-primary bg-primary-light' },
    instagram: { label: 'Instagram Reel', color: 'text-pink-700 bg-pink-100' },
  };

  // 상태별 스타일
  const statusStyles: Record<VideoDownloadStatus, { label: string; color: string }> = {
    pending: { label: '대기중', color: 'text-muted-foreground bg-muted' },
    picked: { label: '준비중', color: 'text-warning-foreground bg-warning-light' },
    processing: { label: '다운로드중', color: 'text-primary bg-primary-light' },
    completed: { label: '완료', color: 'text-success bg-success-light' },
    failed: { label: '실패', color: 'text-error bg-error-light' },
    cancelled: { label: '취소됨', color: 'text-muted-foreground bg-background' },
  };

  async function fetchDownloads() {
    loading = true;
    error = null;
    try {
      const params: { status?: string; download_type?: string; page?: number; page_size?: number } = {
        page,
        page_size: pageSize,
      };
      if (statusFilter) params.status = statusFilter;
      if (typeFilter) params.download_type = typeFilter;

      const result = await videoDownloadApi.list(params);
      downloads = result.items;
      total = result.total;
      totalPages = result.total_pages;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  async function fetchStats() {
    try {
      stats = await videoDownloadApi.stats();
    } catch (e) {
      console.error('통계 로드 실패:', e);
    }
  }

  async function handleSubmit() {
    if (batchMode) {
      await handleBatchSubmit();
      return;
    }

    if (!newUrl.trim()) return;

    isSubmitting = true;
    try {
      await videoDownloadApi.create({
        url: newUrl.trim(),
        download_type: newType || undefined,
        quality: newQuality,
        embedding_url: newEmbeddingUrl || undefined,
        output_filename: newOutputFilename.trim() || undefined,
      });

      // 폼 초기화
      resetForm();

      // 새로고침
      await Promise.all([fetchDownloads(), fetchStats()]);
    } catch (e) {
      alert(e instanceof Error ? e.message : '다운로드 요청 실패');
    } finally {
      isSubmitting = false;
    }
  }

  async function handleBatchSubmit() {
    const validUrls = batchUrls.filter(url => url.trim());
    if (validUrls.length === 0) {
      alert('URL을 입력해주세요.');
      return;
    }

    isSubmitting = true;
    try {
      const result = await videoDownloadApi.createBatch({
        urls: validUrls.map(url => url.trim()),
        download_type: newType || undefined,
        quality: newQuality,
        embedding_url: newEmbeddingUrl || undefined,
        output_prefix: batchOutputPrefix.trim() || undefined,
      });

      alert(result.message);

      // 폼 초기화
      resetForm();

      // 새로고침
      await Promise.all([fetchDownloads(), fetchStats()]);
    } catch (e) {
      alert(e instanceof Error ? e.message : '배치 다운로드 요청 실패');
    } finally {
      isSubmitting = false;
    }
  }

  function resetForm() {
    newUrl = '';
    newType = '';
    newQuality = 'best';
    newEmbeddingUrl = '';
    newOutputFilename = '';
    batchUrls = [''];
    batchOutputPrefix = '';
    batchMode = false;
    showAddModal = false;
  }

  function addBatchUrl() {
    batchUrls = [...batchUrls, ''];
  }

  function removeBatchUrl(index: number) {
    if (batchUrls.length > 1) {
      batchUrls = batchUrls.filter((_, i) => i !== index);
    }
  }

  function updateBatchUrl(index: number, value: string) {
    batchUrls[index] = value;
    batchUrls = batchUrls;
  }

  // Vimeo 감지 (타입 선택 또는 URL에 vimeo 포함)
  $: hasVimeoUrl = newType === 'vimeo' || (batchMode
    ? batchUrls.some(url => url.toLowerCase().includes('vimeo'))
    : newUrl.toLowerCase().includes('vimeo'));

  // 유효한 URL 개수
  $: validUrlCount = batchUrls.filter(url => url.trim()).length;

  async function handleCancel(id: number) {
    if (!confirm('다운로드를 취소하시겠습니까?')) return;

    try {
      await videoDownloadApi.cancel(id);
      await Promise.all([fetchDownloads(), fetchStats()]);
    } catch (e) {
      alert(e instanceof Error ? e.message : '취소 실패');
    }
  }

  async function handleRetry(id: number) {
    try {
      await videoDownloadApi.retry(id);
      await Promise.all([fetchDownloads(), fetchStats()]);
    } catch (e) {
      alert(e instanceof Error ? e.message : '재시도 실패');
    }
  }

  async function handleDelete(id: number) {
    if (!confirm('이 다운로드 기록을 삭제하시겠습니까?')) return;

    try {
      await videoDownloadApi.delete(id);
      await Promise.all([fetchDownloads(), fetchStats()]);
    } catch (e) {
      alert(e instanceof Error ? e.message : '삭제 실패');
    }
  }

  function handleFilterChange() {
    page = 1;
    fetchDownloads();
  }

  function handlePageChange(newPage: number) {
    page = newPage;
    fetchDownloads();
  }

  function formatBytes(bytes: number | null): string {
    if (!bytes) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
      size /= 1024;
      i++;
    }
    return `${size.toFixed(1)} ${units[i]}`;
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function truncateUrl(url: string, maxLength = 60): string {
    if (url.length <= maxLength) return url;
    return url.slice(0, maxLength) + '...';
  }

  onMount(() => {
    Promise.all([fetchDownloads(), fetchStats()]);

    // 5초마다 자동 새로고침 (진행중인 다운로드 확인용)
    refreshInterval = setInterval(() => {
      if (autoRefresh) {
        fetchDownloads();
        fetchStats();
      }
    }, 5000);
  });

  onDestroy(() => {
    if (refreshInterval) {
      clearInterval(refreshInterval);
    }
  });
</script>

<div>
  <!-- 헤더 -->
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-2xl font-bold text-foreground">비디오 다운로드</h1>
      <p class="text-sm text-muted-foreground mt-1">YouTube, Vimeo, Instagram Reel 다운로드 큐</p>
    </div>
    <button
      onclick={() => showAddModal = true}
      class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors flex items-center gap-2"
    >
      <span class="text-lg">+</span>
      새 다운로드
    </button>
  </div>

  <!-- 통계 카드 -->
  {#if stats}
    <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
      <div class="bg-white rounded-lg p-3 border border-border">
        <div class="text-xs text-muted-foreground">전체</div>
        <div class="text-xl font-bold text-foreground">{stats.total}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-border">
        <div class="text-xs text-muted-foreground">대기중</div>
        <div class="text-xl font-bold text-muted-foreground">{stats.pending}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-border">
        <div class="text-xs text-muted-foreground">진행중</div>
        <div class="text-xl font-bold text-primary">{stats.processing + stats.picked}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-border">
        <div class="text-xs text-muted-foreground">완료</div>
        <div class="text-xl font-bold text-success">{stats.completed}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-border">
        <div class="text-xs text-muted-foreground">실패</div>
        <div class="text-xl font-bold text-error">{stats.failed}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-border">
        <div class="text-xs text-muted-foreground">취소</div>
        <div class="text-xl font-bold text-muted-foreground">{stats.cancelled}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-border flex items-center gap-2">
        <input
          type="checkbox"
          id="autoRefresh"
          bind:checked={autoRefresh}
          class="rounded"
        />
        <label for="autoRefresh" class="text-xs text-muted-foreground cursor-pointer">자동 새로고침</label>
      </div>
    </div>
  {/if}

  <!-- 필터 -->
  <div class="bg-white rounded-lg p-4 border border-border mb-4">
    <div class="flex flex-wrap gap-4">
      <div>
        <label for="statusFilter" class="block text-xs text-muted-foreground mb-1">상태</label>
        <select
          id="statusFilter"
          bind:value={statusFilter}
          onchange={handleFilterChange}
          class="px-3 py-1.5 border border-border rounded-md text-sm"
        >
          <option value="">전체</option>
          <option value="pending">대기중</option>
          <option value="processing">다운로드중</option>
          <option value="completed">완료</option>
          <option value="failed">실패</option>
          <option value="cancelled">취소됨</option>
        </select>
      </div>
      <div>
        <label for="typeFilter" class="block text-xs text-muted-foreground mb-1">타입</label>
        <select
          id="typeFilter"
          bind:value={typeFilter}
          onchange={handleFilterChange}
          class="px-3 py-1.5 border border-border rounded-md text-sm"
        >
          <option value="">전체</option>
          <option value="youtube">YouTube</option>
          <option value="youtube_stream">YouTube Live</option>
          <option value="vimeo">Vimeo</option>
          <option value="instagram">Instagram Reel</option>
        </select>
      </div>
    </div>
  </div>

  <!-- 다운로드 목록 -->
  {#if loading && downloads.length === 0}
    <div class="bg-white rounded-lg p-12 border border-border text-center">
      <div class="animate-spin w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full mx-auto mb-4"></div>
      <p class="text-muted-foreground">로딩중...</p>
    </div>
  {:else if error}
    <div class="bg-error-light rounded-lg p-4 border border-red-200 text-error">
      {error}
    </div>
  {:else if downloads.length === 0}
    <div class="bg-white rounded-lg p-12 border border-border text-center">
      <p class="text-muted-foreground mb-4">다운로드 요청이 없습니다.</p>
      <button
        onclick={() => showAddModal = true}
        class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover"
      >
        새 다운로드 추가
      </button>
    </div>
  {:else}
    <div class="bg-white rounded-lg border border-border overflow-hidden">
      <table class="w-full">
        <thead class="bg-background border-b border-border">
          <tr>
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">타입</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">URL / 제목</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">상태</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">진행률</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">크기</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">생성일</th>
            <th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">액션</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          {#each downloads as download (download.id)}
            <tr class="hover:bg-muted">
              <td class="px-4 py-3">
                <span class="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium {typeStyles[download.download_type]?.color || 'text-muted-foreground bg-muted'}">
                  {#if download.download_type === 'youtube'}
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>
                  {:else if download.download_type === 'youtube_stream'}
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"/></svg>
                  {:else if download.download_type === 'vimeo'}
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20.2 6 3 11l-.9-2.4c-.3-.7-.1-1.4.5-1.7l15.4-4.5c.7-.2 1.4.1 1.7.9l.5 2.7Z"/><path d="M4 11v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10l-16 1Z"/></svg>
                  {:else if download.download_type === 'instagram'}
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1"/></svg>
                  {/if}
                  {typeStyles[download.download_type]?.label || download.download_type}
                </span>
              </td>
              <td class="px-4 py-3">
                <div class="max-w-md">
                  {#if download.output_filename}
                    <div class="font-medium text-foreground truncate" title={download.output_filename}>{download.output_filename}</div>
                  {/if}
                  {#if download.title}
                    <div class="text-xs text-muted-foreground truncate" title={download.title}>{download.title}</div>
                  {/if}
                  <a
                    href={download.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-xs text-primary hover:underline truncate block"
                    title={download.url}
                  >
                    {truncateUrl(download.url)}
                  </a>
                </div>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center px-2 py-1 rounded text-xs font-medium {statusStyles[download.status]?.color || 'text-muted-foreground bg-muted'}">
                  {statusStyles[download.status]?.label || download.status}
                </span>
                {#if download.error_message}
                  <div class="text-xs text-error mt-1 truncate max-w-32" title={download.error_message}>
                    {download.error_message}
                  </div>
                {/if}
              </td>
              <td class="px-4 py-3">
                {#if download.status === 'processing'}
                  <div class="w-24">
                    <div class="h-2 bg-secondary rounded-full overflow-hidden">
                      <div
                        class="h-full bg-primary transition-all duration-300"
                        style="width: {download.progress}%"
                      ></div>
                    </div>
                    <div class="text-xs text-muted-foreground mt-1">{download.progress}%</div>
                  </div>
                {:else if download.status === 'completed'}
                  <span class="text-success text-sm">100%</span>
                {:else}
                  <span class="text-muted-foreground text-sm">-</span>
                {/if}
              </td>
              <td class="px-4 py-3 text-sm text-muted-foreground">
                {formatBytes(download.file_size)}
              </td>
              <td class="px-4 py-3 text-sm text-muted-foreground">
                {formatDate(download.created_at)}
              </td>
              <td class="px-4 py-3 text-right">
                <div class="flex items-center justify-end gap-2">
                  {#if download.status === 'pending' || download.status === 'picked' || download.status === 'processing'}
                    <button
                      onclick={() => handleCancel(download.id)}
                      class="text-xs text-error hover:text-error"
                    >
                      취소
                    </button>
                  {:else if download.status === 'failed' || download.status === 'cancelled'}
                    <button
                      onclick={() => handleRetry(download.id)}
                      class="text-xs text-primary hover:text-primary-hover"
                    >
                      재시도
                    </button>
                    <button
                      onclick={() => handleDelete(download.id)}
                      class="text-xs text-muted-foreground hover:text-error"
                    >
                      삭제
                    </button>
                  {:else if download.status === 'completed'}
                    {#if download.output_path}
                      <span class="text-xs text-muted-foreground" title={download.output_path}>
                        저장됨
                      </span>
                    {/if}
                    <button
                      onclick={() => handleDelete(download.id)}
                      class="text-xs text-muted-foreground hover:text-error"
                    >
                      삭제
                    </button>
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- 페이지네이션 -->
    {#if totalPages > 1}
      <div class="flex items-center justify-between mt-4">
        <div class="text-sm text-muted-foreground">
          총 {total}개 중 {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)}개
        </div>
        <div class="flex items-center gap-2">
          <button
            onclick={() => handlePageChange(page - 1)}
            disabled={!canPrevPage}
            class="px-3 py-1 border border-border rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
          >
            이전
          </button>
          <span class="text-sm text-muted-foreground">
            {page} / {totalPages}
          </span>
          <button
            onclick={() => handlePageChange(page + 1)}
            disabled={!canNextPage}
            class="px-3 py-1 border border-border rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
          >
            다음
          </button>
        </div>
      </div>
    {/if}
  {/if}
</div>

<!-- 새 다운로드 모달 -->
{#if showAddModal}
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
    <div class="bg-white rounded-lg w-full max-w-lg mx-4 overflow-hidden shadow-xl max-h-[90vh] flex flex-col">
      <div class="px-6 py-4 border-b border-border flex items-center justify-between">
        <h2 class="text-lg font-semibold text-foreground">새 다운로드</h2>
        <label class="flex items-center gap-2 cursor-pointer">
          <span class="text-sm text-muted-foreground">배치 모드</span>
          <button
            type="button"
            onclick={() => batchMode = !batchMode}
            class="relative w-11 h-6 rounded-full transition-colors {batchMode ? 'bg-primary' : 'bg-gray-300'}"
          >
            <span
              class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform {batchMode ? 'translate-x-5' : ''}"
            ></span>
          </button>
        </label>
      </div>

      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="p-6 space-y-4 overflow-y-auto flex-1">
        {#if batchMode}
          <!-- 배치 모드: 복수 URL 입력 -->
          <div>
            <label class="block text-sm font-medium text-foreground mb-2">
              URL 목록 <span class="text-error">*</span>
            </label>
            <div class="space-y-2 max-h-48 overflow-y-auto">
              {#each batchUrls as url, index}
                <div class="flex items-center gap-2">
                  <input
                    type="url"
                    value={url}
                    oninput={(e) => updateBatchUrl(index, (e.target as HTMLInputElement).value)}
                    placeholder="https://www.instagram.com/reel/... 또는 https://vimeo.com/..."
                    class="flex-1 px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring text-sm"
                  />
                  <button
                    type="button"
                    onclick={() => removeBatchUrl(index)}
                    disabled={batchUrls.length === 1}
                    class="p-2 text-muted-foreground hover:text-error disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                  </button>
                </div>
              {/each}
            </div>
            <button
              type="button"
              onclick={addBatchUrl}
              class="mt-2 text-sm text-primary hover:text-primary-hover flex items-center gap-1"
            >
              <span class="text-lg">+</span> URL 추가
            </button>
          </div>

          <div>
            <label for="batchOutputPrefix" class="block text-sm font-medium text-foreground mb-1">
              파일명 접두사 (선택)
            </label>
            <input
              type="text"
              id="batchOutputPrefix"
              bind:value={batchOutputPrefix}
              placeholder="course_01_"
              class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
            />
            <p class="text-xs text-muted-foreground mt-1">입력시 파일명이 접두사01, 접두사02... 형태로 저장</p>
          </div>
        {:else}
          <!-- 단일 모드: 기존 UI -->
          <div>
            <label for="url" class="block text-sm font-medium text-foreground mb-1">
              URL <span class="text-error">*</span>
            </label>
            <input
              type="url"
              id="url"
              bind:value={newUrl}
              placeholder="https://www.instagram.com/reel/... 또는 https://www.youtube.com/watch?v=..."
              required
              class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
            />
            <p class="text-xs text-muted-foreground mt-1">YouTube, YouTube Live, Vimeo, Instagram Reel URL 지원</p>
          </div>

          <div>
            <label for="outputFilename" class="block text-sm font-medium text-foreground mb-1">
              파일명 (선택)
            </label>
            <input
              type="text"
              id="outputFilename"
              bind:value={newOutputFilename}
              placeholder="저장할 파일명 (확장자 제외)"
              class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
            />
            <p class="text-xs text-muted-foreground mt-1">미입력 시 영상 제목으로 자동 설정</p>
          </div>
        {/if}

        <!-- 공통 설정 -->
        <div>
          <label for="type" class="block text-sm font-medium text-foreground mb-1">
            다운로드 타입
          </label>
          <select
            id="type"
            bind:value={newType}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
          >
            <option value="">자동 감지</option>
            <option value="youtube">YouTube (일반 영상)</option>
            <option value="youtube_stream">YouTube Live (스트림)</option>
            <option value="vimeo">Vimeo</option>
            <option value="instagram">Instagram Reel</option>
          </select>
          <p class="text-xs text-muted-foreground mt-1">Instagram은 1차로 공개 Reel만 지원하며 로그인 필요/비공개 URL은 실패할 수 있습니다.</p>
        </div>

        <div>
          <label for="quality" class="block text-sm font-medium text-foreground mb-1">
            화질
          </label>
          <select
            id="quality"
            bind:value={newQuality}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
          >
            <option value="best">최고 화질</option>
            <option value="1080">1080p</option>
            <option value="720">720p</option>
            <option value="480">480p</option>
            <option value="worst">최저 화질</option>
          </select>
        </div>

        {#if hasVimeoUrl}
          <div>
            <label for="embeddingUrl" class="block text-sm font-medium text-foreground mb-1">
              임베드 페이지 URL (선택)
            </label>
            <input
              type="url"
              id="embeddingUrl"
              bind:value={newEmbeddingUrl}
              placeholder="https://example.com/page-with-vimeo"
              class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
            />
            <p class="text-xs text-muted-foreground mt-1">embed-only 비디오의 경우 비디오가 임베드된 페이지 URL 입력 필수</p>
          </div>
        {/if}

        <div class="flex justify-end gap-3 pt-4">
          <button
            type="button"
            onclick={resetForm}
            class="px-4 py-2 text-foreground border border-border rounded-lg hover:bg-muted"
          >
            취소
          </button>
          <button
            type="submit"
            disabled={isSubmitting || (batchMode ? validUrlCount === 0 : !newUrl.trim())}
            class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {#if isSubmitting}
              요청중...
            {:else if batchMode}
              다운로드 요청 ({validUrlCount}개)
            {:else}
              다운로드 요청
            {/if}
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}
