<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { gitReposApi } from '$lib/api/gitRepos';
  import type { GitRepo } from '$lib/types/gitRepos';
  import AddRepoModal from './AddRepoModal.svelte';
  import { createSelection } from '$lib/utils/selection.svelte';

  let repos: GitRepo[] = $state([]);
  let loading = $state(true);
  let refreshing = $state(false);
  let showAddModal = $state(false);

  // 선택 상태
  const selection = createSelection();

  // 일괄 작업 모달
  let batchCommitMsg = $state('');
  let showBatchCommitModal = $state(false);
  let batchWorking = $state(false);

  let error = $state('');
  let toast = $state('');

  // ── 요약 카운트 ──────────────────────────────────
  const total = $derived(repos.length);
  const cleanCount = $derived(repos.filter((r) => r.last_status === 'clean').length);
  const dirtyCount = $derived(repos.filter((r) => r.last_status === 'dirty').length);
  const conflictCount = $derived(repos.filter((r) => r.last_status === 'conflict').length);

  onMount(async () => {
    await loadRepos();
  });

  async function loadRepos() {
    loading = true;
    error = '';
    try {
      // 캐시된 목록 즉시 표시
      repos = await gitReposApi.listRepos();
    } catch (e) {
      error = e instanceof Error ? e.message : '로드 실패';
    } finally {
      loading = false;
    }
    // 백그라운드로 실제 git status 갱신
    refreshing = true;
    try {
      repos = await gitReposApi.refreshAll();
    } catch {
      // 갱신 실패는 조용히 무시 (캐시 데이터 유지)
    } finally {
      refreshing = false;
    }
  }

  async function handleRefreshAll() {
    refreshing = true;
    try {
      repos = await gitReposApi.refreshAll();
      showToast('전체 상태가 갱신되었습니다.');
    } catch (e) {
      error = e instanceof Error ? e.message : '갱신 실패';
    } finally {
      refreshing = false;
    }
  }

  async function handleRefreshOne(id: number) {
    try {
      const updated = await gitReposApi.refreshRepo(id);
      repos = repos.map((r) => (r.id === id ? updated : r));
    } catch (e) {
      showToast('상태 갱신 실패: ' + (e instanceof Error ? e.message : ''), 'error');
    }
  }

  async function handleDelete(id: number) {
    if (!confirm('등록을 해제하시겠습니까?')) return;
    try {
      await gitReposApi.deleteRepo(id);
      repos = repos.filter((r) => r.id !== id);
      if (selection.has(id)) selection.toggle(id);
    } catch (e) {
      showToast('삭제 실패: ' + (e instanceof Error ? e.message : ''), 'error');
    }
  }

  function handleRepoAdded(repo: GitRepo) {
    repos = [...repos, repo];
  }

  async function handleBatchCommit() {
    if (!batchCommitMsg.trim()) return;
    batchWorking = true;
    try {
      const result = await gitReposApi.batchCommit(selection.toArray(), batchCommitMsg);
      const failed = result.results.filter((r) => !r.success);
      if (failed.length) {
        showToast(`${failed.length}개 레포 커밋 실패`, 'error');
      } else {
        showToast('일괄 커밋 완료');
      }
      showBatchCommitModal = false;
      batchCommitMsg = '';
      await handleRefreshAll();
    } catch (e) {
      showToast('일괄 커밋 실패: ' + (e instanceof Error ? e.message : ''), 'error');
    } finally {
      batchWorking = false;
    }
  }

  async function handleBatchPush() {
    if (selection.count === 0) return;
    if (!confirm(`선택한 ${selection.count}개 레포지토리를 푸시하시겠습니까?`)) return;
    batchWorking = true;
    try {
      const result = await gitReposApi.batchPush(selection.toArray());
      const failed = result.results.filter((r) => !r.success);
      if (failed.length) showToast(`${failed.length}개 레포 푸시 실패`, 'error');
      else showToast('일괄 푸시 완료');
      await handleRefreshAll();
    } catch (e) {
      showToast('일괄 푸시 실패: ' + (e instanceof Error ? e.message : ''), 'error');
    } finally {
      batchWorking = false;
    }
  }

  function showToast(msg: string, type: 'success' | 'error' = 'success') {
    toast = msg;
    setTimeout(() => (toast = ''), 3000);
  }

  function statusBadge(status: string | null) {
    switch (status) {
      case 'clean': return { label: 'clean', cls: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' };
      case 'dirty': return { label: 'dirty', cls: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300' };
      case 'conflict': return { label: 'conflict', cls: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300' };
      default: return { label: status || '?', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400' };
    }
  }
</script>

<div class="p-6 max-w-7xl mx-auto">
  <!-- 헤더 -->
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-bold text-gray-800 dark:text-gray-100">📂 Git 레포지토리 관리</h1>
    <div class="flex gap-2">
      <button
        class="px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 dark:text-gray-200 disabled:opacity-50"
        onclick={handleRefreshAll}
        disabled={refreshing}
      >
        {refreshing ? '🔄 갱신 중…' : '🔄 전체 새로고침'}
      </button>
      <button
        class="px-3 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700"
        onclick={() => (showAddModal = true)}
      >
        ➕ 폴더 추가
      </button>
      {#if selection.count > 0}
        <button
          class="px-3 py-2 text-sm rounded-lg bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
          onclick={() => (showBatchCommitModal = true)}
          disabled={batchWorking}
        >커밋 ({selection.count})</button>
        <button
          class="px-3 py-2 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
          onclick={handleBatchPush}
          disabled={batchWorking}
        >푸시 ({selection.count})</button>
      {/if}
    </div>
  </div>

  <!-- 요약 카드 -->
  <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
    <div class="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-100 dark:border-gray-700">
      <p class="text-xs text-gray-500 dark:text-gray-400 mb-1">전체</p>
      <p class="text-2xl font-bold text-gray-800 dark:text-gray-100">{total}</p>
    </div>
    <div class="bg-green-50 dark:bg-green-900/20 rounded-xl p-4 shadow-sm border border-green-100 dark:border-green-800">
      <p class="text-xs text-green-600 dark:text-green-400 mb-1">clean</p>
      <p class="text-2xl font-bold text-green-700 dark:text-green-300">{cleanCount}</p>
    </div>
    <div class="bg-yellow-50 dark:bg-yellow-900/20 rounded-xl p-4 shadow-sm border border-yellow-100 dark:border-yellow-800">
      <p class="text-xs text-yellow-600 dark:text-yellow-400 mb-1">dirty</p>
      <p class="text-2xl font-bold text-yellow-700 dark:text-yellow-300">{dirtyCount}</p>
    </div>
    <div class="bg-red-50 dark:bg-red-900/20 rounded-xl p-4 shadow-sm border border-red-100 dark:border-red-800">
      <p class="text-xs text-red-600 dark:text-red-400 mb-1">conflict</p>
      <p class="text-2xl font-bold text-red-700 dark:text-red-300">{conflictCount}</p>
    </div>
  </div>

  {#if error}
    <div class="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 text-sm">{error}</div>
  {/if}

  <!-- 테이블 -->
  {#if loading}
    <div class="text-center py-16 text-muted-foreground">로딩 중…</div>
  {:else if repos.length === 0}
    <div class="text-center py-16 text-muted-foreground">
      <p class="text-4xl mb-3">📂</p>
      <p>등록된 레포지토리가 없습니다.</p>
      <button
        class="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700"
        onclick={() => (showAddModal = true)}
      >첫 레포지토리 추가</button>
    </div>
  {:else}
    <div class="bg-white dark:bg-gray-800 rounded-xl shadow-sm overflow-hidden border border-gray-100 dark:border-gray-700">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 text-xs uppercase">
          <tr>
            <th class="px-4 py-3 text-left">
              <input
                type="checkbox"
                checked={selection.isAllSelected(repos.map(r => r.id))}
                onchange={() => selection.selectAll(repos.map(r => r.id))}
                class="rounded"
              />
            </th>
            <th class="px-4 py-3 text-left">별칭 / 경로</th>
            <th class="px-4 py-3 text-left">브랜치</th>
            <th class="px-4 py-3 text-left">상태</th>
            <th class="px-4 py-3 text-left">ahead / behind</th>
            <th class="px-4 py-3 text-left">마지막 확인</th>
            <th class="px-4 py-3 text-right">액션</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 dark:divide-gray-700">
          {#each repos as repo (repo.id)}
            {@const badge = statusBadge(repo.last_status)}
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors">
              <!-- 체크박스 -->
              <td class="px-4 py-3">
                <input
                  type="checkbox"
                  checked={selection.has(repo.id)}
                  onchange={() => selection.toggle(repo.id)}
                  class="rounded"
                />
              </td>
              <!-- 별칭 / 경로 -->
              <td class="px-4 py-3">
                <button
                  class="text-left"
                  onclick={() => goto(`/git-repos/${repo.id}`)}
                >
                  <p class="font-medium text-blue-600 dark:text-blue-400 hover:underline">{repo.alias || repo.path.split(/[/\\]/).pop()}</p>
                  <p class="text-xs text-gray-400 dark:text-gray-500 truncate max-w-xs">{repo.path}</p>
                </button>
              </td>
              <!-- 브랜치 -->
              <td class="px-4 py-3 font-mono text-xs text-gray-600 dark:text-gray-300">
                {repo.last_branch || '-'}
              </td>
              <!-- 상태 -->
              <td class="px-4 py-3">
                <span class="inline-flex px-2 py-0.5 rounded-full text-xs font-medium {badge.cls}">{badge.label}</span>
              </td>
              <!-- ahead/behind -->
              <td class="px-4 py-3 text-xs text-gray-500 dark:text-gray-400">
                {#if repo.last_ahead != null || repo.last_behind != null}
                  <span class="text-green-600 dark:text-green-400">↑{repo.last_ahead ?? 0}</span>
                  <span class="mx-1 text-gray-300">/</span>
                  <span class="text-red-500 dark:text-red-400">↓{repo.last_behind ?? 0}</span>
                {:else}
                  -
                {/if}
              </td>
              <!-- 마지막 확인 -->
              <td class="px-4 py-3 text-xs text-gray-400 dark:text-gray-500">
                {repo.last_checked_at ? new Date(repo.last_checked_at).toLocaleTimeString('ko-KR') : '-'}
              </td>
              <!-- 액션 -->
              <td class="px-4 py-3 text-right">
                <div class="flex justify-end gap-1">
                  <button
                    class="px-2 py-1 text-xs rounded bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300"
                    onclick={() => handleRefreshOne(repo.id)}
                    title="상태 새로고침"
                  >🔄</button>
                  <button
                    class="px-2 py-1 text-xs rounded bg-blue-50 dark:bg-blue-900/30 hover:bg-blue-100 dark:hover:bg-blue-800/40 text-blue-600 dark:text-blue-400"
                    onclick={() => goto(`/git-repos/${repo.id}`)}
                    title="상세 보기"
                  >상세</button>
                  <button
                    class="px-2 py-1 text-xs rounded bg-red-50 dark:bg-red-900/30 hover:bg-red-100 dark:hover:bg-red-800/40 text-red-500 dark:text-red-400"
                    onclick={() => handleDelete(repo.id)}
                    title="등록 해제"
                  >삭제</button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<!-- 모달: 폴더 추가 -->
{#if showAddModal}
  <AddRepoModal onClose={() => (showAddModal = false)} onAdded={handleRepoAdded} />
{/if}

<!-- 모달: 일괄 커밋 메시지 입력 -->
{#if showBatchCommitModal}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
    onclick={() => (showBatchCommitModal = false)}
    onkeydown={(e) => e.key === 'Escape' && (showBatchCommitModal = false)}
    role="dialog"
    aria-modal="true"
    tabindex="-1"
  >
    <div
      class="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-md mx-4 p-6"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
      role="presentation"
    >
      <h2 class="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-100">일괄 커밋 ({selection.count}개)</h2>
      <input
        class="w-full border rounded-lg px-3 py-2 text-sm mb-4 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
        placeholder="커밋 메시지"
        bind:value={batchCommitMsg}
        onkeydown={(e) => e.key === 'Enter' && handleBatchCommit()}
      />
      <div class="flex justify-end gap-2">
        <button
          class="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
          onclick={() => (showBatchCommitModal = false)}
        >취소</button>
        <button
          class="px-4 py-2 bg-orange-500 text-white rounded-lg text-sm hover:bg-orange-600 disabled:opacity-50"
          onclick={handleBatchCommit}
          disabled={batchWorking || !batchCommitMsg.trim()}
        >{batchWorking ? '커밋 중…' : '커밋'}</button>
      </div>
    </div>
  </div>
{/if}

<!-- 토스트 -->
{#if toast}
  <div class="fixed bottom-6 right-6 z-50 px-4 py-3 rounded-xl bg-gray-800 text-white text-sm shadow-lg">
    {toast}
  </div>
{/if}
