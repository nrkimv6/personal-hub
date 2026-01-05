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
  let limit = 20;
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
  const typeStyles: Record<VideoDownloadType, { icon: string; label: string; color: string }> = {
    youtube: { icon: '▶', label: 'YouTube', color: 'text-red-600 bg-red-100' },
    youtube_stream: { icon: '🔴', label: 'YouTube Live', color: 'text-red-700 bg-red-200' },
    vimeo: { icon: '🎬', label: 'Vimeo', color: 'text-blue-600 bg-blue-100' },
  };

  // 상태별 스타일
  const statusStyles: Record<VideoDownloadStatus, { label: string; color: string }> = {
    pending: { label: '대기중', color: 'text-gray-600 bg-gray-100' },
    picked: { label: '준비중', color: 'text-yellow-600 bg-yellow-100' },
    processing: { label: '다운로드중', color: 'text-blue-600 bg-blue-100' },
    completed: { label: '완료', color: 'text-green-600 bg-green-100' },
    failed: { label: '실패', color: 'text-red-600 bg-red-100' },
    cancelled: { label: '취소됨', color: 'text-gray-500 bg-gray-50' },
  };

  async function fetchDownloads() {
    loading = true;
    error = null;
    try {
      const params: { status?: string; download_type?: string; page?: number; limit?: number } = {
        page,
        limit,
      };
      if (statusFilter) params.status = statusFilter;
      if (typeFilter) params.download_type = typeFilter;

      const result = await videoDownloadApi.list(params);
      downloads = result.items;
      total = result.total;
      totalPages = result.pages;
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

  // Vimeo 감지 (배치 모드)
  $: hasVimeoUrl = batchMode
    ? batchUrls.some(url => url.toLowerCase().includes('vimeo'))
    : newUrl.toLowerCase().includes('vimeo') || newType === 'vimeo';

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

<svelte:head>
  <title>비디오 다운로드 | Monitor</title>
</svelte:head>

<div class="container mx-auto px-4 py-6 max-w-6xl">
  <!-- 헤더 -->
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-2xl font-bold text-gray-900">비디오 다운로드</h1>
      <p class="text-sm text-gray-500 mt-1">YouTube, Vimeo 영상 다운로드</p>
    </div>
    <button
      onclick={() => showAddModal = true}
      class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
    >
      <span class="text-lg">+</span>
      새 다운로드
    </button>
  </div>

  <!-- 통계 카드 -->
  {#if stats}
    <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
      <div class="bg-white rounded-lg p-3 border border-gray-200">
        <div class="text-xs text-gray-500">전체</div>
        <div class="text-xl font-bold text-gray-900">{stats.total}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-gray-200">
        <div class="text-xs text-gray-500">대기중</div>
        <div class="text-xl font-bold text-gray-600">{stats.pending}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-gray-200">
        <div class="text-xs text-gray-500">진행중</div>
        <div class="text-xl font-bold text-blue-600">{stats.processing + stats.picked}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-gray-200">
        <div class="text-xs text-gray-500">완료</div>
        <div class="text-xl font-bold text-green-600">{stats.completed}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-gray-200">
        <div class="text-xs text-gray-500">실패</div>
        <div class="text-xl font-bold text-red-600">{stats.failed}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-gray-200">
        <div class="text-xs text-gray-500">취소</div>
        <div class="text-xl font-bold text-gray-500">{stats.cancelled}</div>
      </div>
      <div class="bg-white rounded-lg p-3 border border-gray-200 flex items-center gap-2">
        <input
          type="checkbox"
          id="autoRefresh"
          bind:checked={autoRefresh}
          class="rounded"
        />
        <label for="autoRefresh" class="text-xs text-gray-500 cursor-pointer">자동 새로고침</label>
      </div>
    </div>
  {/if}

  <!-- 필터 -->
  <div class="bg-white rounded-lg p-4 border border-gray-200 mb-4">
    <div class="flex flex-wrap gap-4">
      <div>
        <label for="statusFilter" class="block text-xs text-gray-500 mb-1">상태</label>
        <select
          id="statusFilter"
          bind:value={statusFilter}
          onchange={handleFilterChange}
          class="px-3 py-1.5 border border-gray-300 rounded-md text-sm"
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
        <label for="typeFilter" class="block text-xs text-gray-500 mb-1">타입</label>
        <select
          id="typeFilter"
          bind:value={typeFilter}
          onchange={handleFilterChange}
          class="px-3 py-1.5 border border-gray-300 rounded-md text-sm"
        >
          <option value="">전체</option>
          <option value="youtube">YouTube</option>
          <option value="youtube_stream">YouTube Live</option>
          <option value="vimeo">Vimeo</option>
        </select>
      </div>
    </div>
  </div>

  <!-- 다운로드 목록 -->
  {#if loading && downloads.length === 0}
    <div class="bg-white rounded-lg p-12 border border-gray-200 text-center">
      <div class="animate-spin w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full mx-auto mb-4"></div>
      <p class="text-gray-500">로딩중...</p>
    </div>
  {:else if error}
    <div class="bg-red-50 rounded-lg p-4 border border-red-200 text-red-600">
      {error}
    </div>
  {:else if downloads.length === 0}
    <div class="bg-white rounded-lg p-12 border border-gray-200 text-center">
      <p class="text-gray-500 mb-4">다운로드 요청이 없습니다.</p>
      <button
        onclick={() => showAddModal = true}
        class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
      >
        새 다운로드 추가
      </button>
    </div>
  {:else}
    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <table class="w-full">
        <thead class="bg-gray-50 border-b border-gray-200">
          <tr>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">타입</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">URL / 제목</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">진행률</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">크기</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">생성일</th>
            <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">액션</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-200">
          {#each downloads as download (download.id)}
            <tr class="hover:bg-gray-50">
              <td class="px-4 py-3">
                <span class="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium {typeStyles[download.download_type]?.color || 'text-gray-600 bg-gray-100'}">
                  {typeStyles[download.download_type]?.icon || '?'}
                  {typeStyles[download.download_type]?.label || download.download_type}
                </span>
              </td>
              <td class="px-4 py-3">
                <div class="max-w-md">
                  {#if download.output_filename}
                    <div class="font-medium text-gray-900 truncate" title={download.output_filename}>{download.output_filename}</div>
                  {/if}
                  {#if download.title}
                    <div class="text-xs text-gray-500 truncate" title={download.title}>{download.title}</div>
                  {/if}
                  <a
                    href={download.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-xs text-blue-600 hover:underline truncate block"
                    title={download.url}
                  >
                    {truncateUrl(download.url)}
                  </a>
                </div>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center px-2 py-1 rounded text-xs font-medium {statusStyles[download.status]?.color || 'text-gray-600 bg-gray-100'}">
                  {statusStyles[download.status]?.label || download.status}
                </span>
                {#if download.error_message}
                  <div class="text-xs text-red-500 mt-1 truncate max-w-32" title={download.error_message}>
                    {download.error_message}
                  </div>
                {/if}
              </td>
              <td class="px-4 py-3">
                {#if download.status === 'processing'}
                  <div class="w-24">
                    <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        class="h-full bg-blue-600 transition-all duration-300"
                        style="width: {download.progress}%"
                      ></div>
                    </div>
                    <div class="text-xs text-gray-500 mt-1">{download.progress}%</div>
                  </div>
                {:else if download.status === 'completed'}
                  <span class="text-green-600 text-sm">100%</span>
                {:else}
                  <span class="text-gray-400 text-sm">-</span>
                {/if}
              </td>
              <td class="px-4 py-3 text-sm text-gray-600">
                {formatBytes(download.file_size)}
              </td>
              <td class="px-4 py-3 text-sm text-gray-600">
                {formatDate(download.created_at)}
              </td>
              <td class="px-4 py-3 text-right">
                <div class="flex items-center justify-end gap-2">
                  {#if download.status === 'pending' || download.status === 'picked' || download.status === 'processing'}
                    <button
                      onclick={() => handleCancel(download.id)}
                      class="text-xs text-red-600 hover:text-red-800"
                    >
                      취소
                    </button>
                  {:else if download.status === 'failed' || download.status === 'cancelled'}
                    <button
                      onclick={() => handleRetry(download.id)}
                      class="text-xs text-blue-600 hover:text-blue-800"
                    >
                      재시도
                    </button>
                    <button
                      onclick={() => handleDelete(download.id)}
                      class="text-xs text-gray-500 hover:text-red-600"
                    >
                      삭제
                    </button>
                  {:else if download.status === 'completed'}
                    {#if download.output_path}
                      <span class="text-xs text-gray-500" title={download.output_path}>
                        저장됨
                      </span>
                    {/if}
                    <button
                      onclick={() => handleDelete(download.id)}
                      class="text-xs text-gray-500 hover:text-red-600"
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
        <div class="text-sm text-gray-500">
          총 {total}개 중 {(page - 1) * limit + 1}-{Math.min(page * limit, total)}개
        </div>
        <div class="flex items-center gap-2">
          <button
            onclick={() => handlePageChange(page - 1)}
            disabled={!canPrevPage}
            class="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
          >
            이전
          </button>
          <span class="text-sm text-gray-600">
            {page} / {totalPages}
          </span>
          <button
            onclick={() => handlePageChange(page + 1)}
            disabled={!canNextPage}
            class="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
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
      <div class="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
        <h2 class="text-lg font-semibold text-gray-900">새 다운로드</h2>
        <label class="flex items-center gap-2 cursor-pointer">
          <span class="text-sm text-gray-600">배치 모드</span>
          <button
            type="button"
            onclick={() => batchMode = !batchMode}
            class="relative w-11 h-6 rounded-full transition-colors {batchMode ? 'bg-blue-600' : 'bg-gray-300'}"
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
            <label class="block text-sm font-medium text-gray-700 mb-2">
              URL 목록 <span class="text-red-500">*</span>
            </label>
            <div class="space-y-2 max-h-48 overflow-y-auto">
              {#each batchUrls as url, index}
                <div class="flex items-center gap-2">
                  <input
                    type="url"
                    value={url}
                    oninput={(e) => updateBatchUrl(index, (e.target as HTMLInputElement).value)}
                    placeholder="https://vimeo.com/..."
                    class="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  />
                  <button
                    type="button"
                    onclick={() => removeBatchUrl(index)}
                    disabled={batchUrls.length === 1}
                    class="p-2 text-gray-400 hover:text-red-500 disabled:opacity-30 disabled:cursor-not-allowed"
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
              class="mt-2 text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
            >
              <span class="text-lg">+</span> URL 추가
            </button>
          </div>

          <div>
            <label for="batchOutputPrefix" class="block text-sm font-medium text-gray-700 mb-1">
              파일명 접두사 (선택)
            </label>
            <input
              type="text"
              id="batchOutputPrefix"
              bind:value={batchOutputPrefix}
              placeholder="course_01_"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <p class="text-xs text-gray-500 mt-1">입력시 파일명이 접두사01, 접두사02... 형태로 저장</p>
          </div>
        {:else}
          <!-- 단일 모드: 기존 UI -->
          <div>
            <label for="url" class="block text-sm font-medium text-gray-700 mb-1">
              URL <span class="text-red-500">*</span>
            </label>
            <input
              type="url"
              id="url"
              bind:value={newUrl}
              placeholder="https://www.youtube.com/watch?v=..."
              required
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <p class="text-xs text-gray-500 mt-1">YouTube, YouTube Live, Vimeo URL 지원</p>
          </div>

          <div>
            <label for="outputFilename" class="block text-sm font-medium text-gray-700 mb-1">
              파일명 (선택)
            </label>
            <input
              type="text"
              id="outputFilename"
              bind:value={newOutputFilename}
              placeholder="저장할 파일명 (확장자 제외)"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <p class="text-xs text-gray-500 mt-1">미입력 시 영상 제목으로 자동 설정</p>
          </div>
        {/if}

        <!-- 공통 설정 -->
        <div>
          <label for="type" class="block text-sm font-medium text-gray-700 mb-1">
            다운로드 타입
          </label>
          <select
            id="type"
            bind:value={newType}
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">자동 감지</option>
            <option value="youtube">YouTube (일반 영상)</option>
            <option value="youtube_stream">YouTube Live (스트림)</option>
            <option value="vimeo">Vimeo</option>
          </select>
        </div>

        <div>
          <label for="quality" class="block text-sm font-medium text-gray-700 mb-1">
            화질
          </label>
          <select
            id="quality"
            bind:value={newQuality}
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
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
            <label for="embeddingUrl" class="block text-sm font-medium text-gray-700 mb-1">
              임베드 페이지 URL (선택)
            </label>
            <input
              type="url"
              id="embeddingUrl"
              bind:value={newEmbeddingUrl}
              placeholder="https://example.com/page-with-vimeo"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <p class="text-xs text-gray-500 mt-1">embed-only 비디오의 경우 비디오가 임베드된 페이지 URL 입력 필수</p>
          </div>
        {/if}

        <div class="flex justify-end gap-3 pt-4">
          <button
            type="button"
            onclick={resetForm}
            class="px-4 py-2 text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            취소
          </button>
          <button
            type="submit"
            disabled={isSubmitting || (batchMode ? validUrlCount === 0 : !newUrl.trim())}
            class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
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
