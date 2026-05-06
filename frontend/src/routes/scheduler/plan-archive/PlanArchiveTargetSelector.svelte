<script lang="ts">
	import { onMount } from 'svelte';
	import { loadSavedTargets, saveTargets, type SelectedTarget } from './planArchiveOperationsState.js';

	interface Props {
		selectedTargets?: SelectedTarget[];
		onchange?: (targets: SelectedTarget[]) => void;
	}

	let { selectedTargets = $bindable([]), onchange }: Props = $props();

	const DEFAULT_TARGETS: SelectedTarget[] = [
		{ provider: 'claude', model: 'claude-opus-4-5', profile_key: null },
		{ provider: 'gemini', model: 'gemini-2.0-flash', profile_key: null },
		{ provider: 'codex', model: 'gpt-5.5', profile_key: null },
	];

	let targets = $state<SelectedTarget[]>(DEFAULT_TARGETS);

	onMount(() => {
		const saved = loadSavedTargets();
		if (saved.length > 0) {
			selectedTargets = saved;
		}
	});

	function isSelected(t: SelectedTarget): boolean {
		return selectedTargets.some(
			(s) => s.provider === t.provider && s.model === t.model && s.profile_key === t.profile_key
		);
	}

	function toggle(t: SelectedTarget) {
		let next: SelectedTarget[];
		if (isSelected(t)) {
			next = selectedTargets.filter(
				(s) => !(s.provider === t.provider && s.model === t.model && s.profile_key === t.profile_key)
			);
		} else {
			next = [...selectedTargets, t];
		}
		selectedTargets = next;
		saveTargets(next);
		onchange?.(next);
	}

	function targetLabel(t: SelectedTarget): string {
		const parts = [t.provider, t.model];
		if (t.profile_key) parts.push(`[${t.profile_key}]`);
		return parts.join('/');
	}
</script>

<div class="flex flex-wrap items-center gap-2">
	<span class="text-xs font-medium text-muted-foreground">분석 Target:</span>
	{#each targets as t}
		{@const checked = isSelected(t)}
		<label class="inline-flex cursor-pointer items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-muted {checked ? 'border-primary bg-primary/10' : ''}">
			<input
				type="checkbox"
				class="accent-primary"
				{checked}
				onchange={() => toggle(t)}
			/>
			{targetLabel(t)}
		</label>
	{/each}
	{#if selectedTargets.length === 0}
		<span class="text-xs text-yellow-600">target을 1개 이상 선택하세요</span>
	{/if}
</div>
