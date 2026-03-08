<script lang="ts">
  import { onMount } from 'svelte';
  import { devRunnerSettingsApi, type DevRunnerSettings } from '$lib/api/dev-runner';
  import { devRunnerRunnerApi } from '$lib/api/dev-runner';

  interface Props { compact?: boolean; }
  let { compact = false }: Props = $props();

  let settings: DevRunnerSettings | null = null;
  let inputValue = 3;
  let saving = false;
  let toast = '';
  let toastTimer: ReturnType<typeof setTimeout>;
  let activeRunnerCount = 0;
  let loading = true;
  let error = $state('');

  onMount(async () => {
    try {
      const [s, runners] = await Promise.all([
        devRunnerSettingsApi.get(),
        devRunnerRunnerApi.runners(),
      ]);
      settings = s;
      inputValue = s.max_concurrent_runners;
      activeRunnerCount = runners.filter((r: any) => r.running).length;
    } catch (e) {
      error = '설정 불러오기 실패';
    } finally {
      loading = false;
    }
  });

  async function handleSave() {
    saving = true;
    error = '';
    try {
      settings = await devRunnerSettingsApi.update(inputValue);
      showToast('저장됨');
    } catch (e: unknown) {
      error = (e as Error)?.message ?? '저장 실패';
    } finally {
      saving = false;
    }
  }

  function showToast(msg: string) {
    toast = msg;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = ''), 2000);
  }
</script>

<div class="settings-panel" class:compact>
  {#if !compact}<h3 class="title">Dev Runner 설정</h3>{/if}

  {#if loading}
    <p class="muted">불러오는 중...</p>
  {:else}
    <div class="field">
      <label for="max-runners">최대 동시 실행 수</label>
      <div class="row">
        <input
          id="max-runners"
          type="number"
          min="1"
          max="10"
          bind:value={inputValue}
          disabled={saving}
        />
        <button on:click={handleSave} disabled={saving}>
          {saving ? '저장 중...' : '저장'}
        </button>
      </div>
      <p class="hint">현재 {activeRunnerCount}개 실행 중 · 허용 최대: {settings?.max_concurrent_runners ?? inputValue}개</p>
      {#if settings?.updated_at}
        <p class="hint">최종 변경: {new Date(settings.updated_at).toLocaleString()}</p>
      {/if}
    </div>

    {#if error}
      <p class="error">{error}</p>
    {/if}

    {#if toast}
      <div class="toast">{toast}</div>
    {/if}
  {/if}
</div>

<style>
  .settings-panel {
    padding: 1rem;
    max-width: 400px;
  }
  .settings-panel.compact {
    padding: 0.625rem;
    max-width: 100%;
  }
  .title {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 1rem;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  label {
    font-size: 0.85rem;
    font-weight: 500;
  }
  .row {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  input[type='number'] {
    width: 80px;
    padding: 0.3rem 0.5rem;
    border: 1px solid #ccc;
    border-radius: 4px;
  }
  button {
    padding: 0.3rem 0.8rem;
    background: #2563eb;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.85rem;
  }
  button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .hint {
    font-size: 0.75rem;
    color: #6b7280;
    margin: 0;
  }
  .error {
    color: #dc2626;
    font-size: 0.8rem;
  }
  .toast {
    margin-top: 0.5rem;
    background: #16a34a;
    color: white;
    padding: 0.3rem 0.7rem;
    border-radius: 4px;
    font-size: 0.8rem;
    display: inline-block;
  }
  .muted {
    color: #9ca3af;
    font-size: 0.85rem;
  }
</style>
