<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  const dispatch = createEventDispatcher<{
    change: { value: string | null };
  }>();

  export let value: string | null = null;
  export let suggestions: string[] = [];
  export let disabled = false;
  export let saving = false;

  let draft = '';
  let dirty = false;
  let incoming = '';

  $: incoming = value ?? '';
  $: if (!dirty && incoming !== draft) {
    draft = incoming;
  }

  function normalize(input: string): string | null {
    const trimmed = input.trim();
    return trimmed.length > 0 ? trimmed : null;
  }

  function submit() {
    if (disabled || saving) return;
    dirty = false;
    dispatch('change', { value: normalize(draft) });
  }

  function clear() {
    if (disabled || saving) return;
    draft = '';
    dirty = false;
    dispatch('change', { value: null });
  }
</script>

<div class="flex flex-wrap items-center gap-2">
  <label class="text-xs text-muted-foreground" for="slide-tag-input">태그</label>
  <input
    id="slide-tag-input"
    type="text"
    class="input input-bordered input-sm min-w-[180px] flex-1"
    list="slide-tag-suggestions"
    bind:value={draft}
    disabled={disabled || saving}
    placeholder="예: 발표 1부, Q&A"
    oninput={() => (dirty = true)}
    onkeydown={(event) => event.key === 'Enter' && submit()}
  />
  <datalist id="slide-tag-suggestions">
    {#each suggestions as tag}
      <option value={tag} />
    {/each}
  </datalist>
  <button type="button" class="btn btn-outline btn-sm" onclick={submit} disabled={disabled || saving}>
    {saving ? '저장 중...' : '저장'}
  </button>
  <button type="button" class="btn btn-ghost btn-sm" onclick={clear} disabled={disabled || saving || !value}>
    태그 제거
  </button>
</div>
