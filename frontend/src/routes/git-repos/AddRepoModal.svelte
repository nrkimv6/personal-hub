<script lang="ts">
  import { gitReposApi } from '$lib/api/gitRepos';
  import type { GitRepo } from '$lib/types/gitRepos';

  interface Props {
    onClose: () => void;
    onAdded: (repo: GitRepo) => void;
  }

  let { onClose, onAdded }: Props = $props();

  let basePath = $state('');
  let discovered: string[] = $state([]);
  let selected: Set<string> = $state(new Set());
  let manualPath = $state('');
  let alias = $state('');
  let loadingDiscover = $state(false);
  let loadingAdd = $state(false);
  let error = $state('');

  async function handleDiscover() {
    if (!basePath.trim()) return;
    loadingDiscover = true;
    error = '';
    try {
      const result = await gitReposApi.discoverRepos(basePath.trim());
      discovered = result.paths;
      if (result.count === 0) error = '해당 경로에서 git 레포지토리를 찾을 수 없습니다.';
    } catch (e) {
      error = e instanceof Error ? e.message : '탐색 실패';
    } finally {
      loadingDiscover = false;
    }
  }

  function toggleSelect(path: string) {
    const next = new Set(selected);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    selected = next;
  }

  async function handleAdd() {
    const paths = [...selected];
    if (manualPath.trim()) paths.push(manualPath.trim());
    if (paths.length === 0) {
      error = '추가할 경로를 선택하거나 직접 입력하세요.';
      return;
    }

    loadingAdd = true;
    error = '';
    let lastRepo: GitRepo | null = null;
    for (const path of paths) {
      try {
        lastRepo = await gitReposApi.createRepo({ path, alias: alias || undefined });
        onAdded(lastRepo);
      } catch (e) {
        error += `${path}: ${e instanceof Error ? e.message : '등록 실패'}\n`;
      }
    }
    loadingAdd = false;
    if (!error) onClose();
  }
</script>

<!-- 모달 오버레이 -->
<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
  onclick={() => onClose()}
  onkeydown={(e) => e.key === 'Escape' && onClose()}
  role="dialog"
  aria-modal="true"
  tabindex="-1"
>
  <div
    class="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg mx-4 p-6"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
    role="presentation"
  >
    <h2 class="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-100">레포지토리 추가</h2>

    <!-- 탐색 -->
    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-1">기본 경로 탐색</label>
      <div class="flex gap-2">
        <input
          class="flex-1 border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          placeholder="예: D:\work\project"
          bind:value={basePath}
          onkeydown={(e) => e.key === 'Enter' && handleDiscover()}
        />
        <button
          class="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
          onclick={handleDiscover}
          disabled={loadingDiscover}
        >
          {loadingDiscover ? '탐색 중…' : '탐색'}
        </button>
      </div>
    </div>

    <!-- 탐색 결과 -->
    {#if discovered.length > 0}
      <div class="mb-4 max-h-48 overflow-y-auto border rounded-lg dark:border-gray-600">
        {#each discovered as path}
          <label class="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer text-sm text-gray-700 dark:text-gray-300">
            <input
              type="checkbox"
              checked={selected.has(path)}
              onchange={() => toggleSelect(path)}
              class="rounded"
            />
            <span class="truncate">{path}</span>
          </label>
        {/each}
      </div>
    {/if}

    <!-- 직접 입력 -->
    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-1">직접 경로 입력</label>
      <input
        class="w-full border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
        placeholder="예: D:\work\project\my-repo"
        bind:value={manualPath}
      />
    </div>

    <!-- 별칭 -->
    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-600 dark:text-gray-400 mb-1">별칭 (선택)</label>
      <input
        class="w-full border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
        placeholder="표시 이름 (비우면 폴더명 사용)"
        bind:value={alias}
      />
    </div>

    {#if error}
      <p class="text-red-500 text-sm mb-3 whitespace-pre-wrap">{error}</p>
    {/if}

    <div class="flex justify-end gap-2">
      <button
        class="px-4 py-2 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
        onclick={onClose}
      >취소</button>
      <button
        class="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
        onclick={handleAdd}
        disabled={loadingAdd}
      >
        {loadingAdd ? '추가 중…' : '추가'}
      </button>
    </div>
  </div>
</div>
