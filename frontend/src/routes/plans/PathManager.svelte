<script lang="ts">
  import { onMount } from 'svelte';
  import { devRunnerPlanApi, type RegisteredPathResponse } from '$lib/api/dev-runner';

  let { onChanged }: { onChanged: () => void } = $props();

  let paths: RegisteredPathResponse[] = [];
  let loading = $state(true);
  let error = $state('');

  let mode = $state<'path' | 'project'>('path');

  let inputPath = $state('');
  let inputType = $state<'plan' | 'archive'>('plan');
  let addError = $state('');
  let adding = $state(false);

  let projectPath = $state('');
  let projectError = $state('');
  let projectResult = $state('');
  let addingProject = $state(false);

  async function loadPaths() {
    loading = true;
    error = '';
    try {
      paths = await devRunnerPlanApi.listPaths();
    } catch (e) {
      error = e instanceof Error ? e.message : '경로 목록 로드 실패';
    } finally {
      loading = false;
    }
  }

  async function handleRemove(path: string) {
    if (!confirm('경로를 제거하시겠습니까?')) return;
    try {
      await devRunnerPlanApi.removePath(path);
      onChanged();
      await loadPaths();
    } catch (e) {
      error = e instanceof Error ? e.message : '경로 제거 실패';
    }
  }

  async function handleAdd() {
    if (!inputPath.trim()) return;
    adding = true;
    addError = '';
    try {
      await devRunnerPlanApi.addPath(inputPath.trim());
      inputPath = '';
      onChanged();
      await loadPaths();
    } catch (e) {
      addError = e instanceof Error ? e.message : '경로 추가 실패';
    } finally {
      adding = false;
    }
  }

  async function handleAddProject() {
    if (!projectPath.trim()) return;
    addingProject = true;
    projectError = '';
    projectResult = '';
    try {
      const result = await devRunnerPlanApi.addProject(projectPath.trim());
      projectResult = `추가 ${result.added.length}개, 건너뜀 ${result.skipped.length}개`;
      projectPath = '';
      onChanged();
      await loadPaths();
    } catch (e) {
      projectError = e instanceof Error ? e.message : '프로젝트 추가 실패';
    } finally {
      addingProject = false;
    }
  }

  onMount(loadPaths);
</script>

<div class="border border-border rounded p-3 bg-muted/30 flex flex-col gap-3 text-sm">
  <h4 class="text-xs font-semibold text-foreground">경로 관리</h4>

  {#if error}
    <p class="text-xs text-red-500">{error}</p>
  {/if}

  {#if loading}
    <p class="text-xs text-muted-foreground">로드 중...</p>
  {:else if paths.length === 0}
    <p class="text-xs text-muted-foreground">등록된 경로가 없습니다.</p>
  {:else}
    <div class="flex flex-col gap-1">
      {#each paths as p (p.path)}
        <div class="flex items-center gap-2 py-1 border-b border-border last:border-0">
          <span class="flex-1 text-xs font-mono truncate text-foreground" title={p.path}>{p.path}</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded {p.path_type === 'plan' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' : 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'}">
            {p.path_type}
          </span>
          <span class="text-[10px] text-muted-foreground">{p.plan_count}개</span>
          <button
            class="text-xs text-red-500 hover:text-red-700 px-1"
            onclick={() => handleRemove(p.path)}
            title="경로 제거"
          >×</button>
        </div>
      {/each}
    </div>
  {/if}

  <!-- 모드 탭 -->
  <div class="flex gap-1 border-t border-border pt-2">
    <button
      class="text-xs px-2 py-0.5 rounded {mode === 'path' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => { mode = 'path'; addError = ''; projectError = ''; projectResult = ''; }}
    >경로 추가</button>
    <button
      class="text-xs px-2 py-0.5 rounded {mode === 'project' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => { mode = 'project'; addError = ''; projectError = ''; projectResult = ''; }}
    >프로젝트 추가</button>
  </div>

  {#if mode === 'path'}
    <!-- 개별 경로 추가 폼 -->
    <div class="flex flex-col gap-1">
      <div class="flex gap-1">
        <input
          type="text"
          placeholder="경로 입력"
          bind:value={inputPath}
          class="flex-1 text-xs px-2 py-1 border border-border rounded bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          onkeydown={(e) => { if (e.key === 'Enter') handleAdd(); }}
        />
        <select
          bind:value={inputType}
          class="text-xs px-2 py-1 border border-border rounded bg-background text-foreground focus:outline-none"
        >
          <option value="plan">plan</option>
          <option value="archive">archive</option>
        </select>
        <button
          class="text-xs px-3 py-1 rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          disabled={adding || !inputPath.trim()}
          onclick={handleAdd}
        >{adding ? '추가 중...' : '추가'}</button>
      </div>
      {#if addError}
        <p class="text-xs text-red-500">{addError}</p>
      {/if}
    </div>
  {:else}
    <!-- 프로젝트 루트 추가 폼 (docs/plan + docs/archive 동시 등록) -->
    <div class="flex flex-col gap-1">
      <p class="text-[10px] text-muted-foreground">프로젝트 루트를 입력하면 docs/plan과 docs/archive를 자동 등록합니다.</p>
      <div class="flex gap-1">
        <input
          type="text"
          placeholder="프로젝트 루트 경로"
          bind:value={projectPath}
          class="flex-1 text-xs px-2 py-1 border border-border rounded bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          onkeydown={(e) => { if (e.key === 'Enter') handleAddProject(); }}
        />
        <button
          class="text-xs px-3 py-1 rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          disabled={addingProject || !projectPath.trim()}
          onclick={handleAddProject}
        >{addingProject ? '추가 중...' : '프로젝트 추가'}</button>
      </div>
      {#if projectError}
        <p class="text-xs text-red-500">{projectError}</p>
      {/if}
      {#if projectResult}
        <p class="text-xs text-green-600">{projectResult}</p>
      {/if}
    </div>
  {/if}
</div>
