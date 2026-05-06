<script lang="ts">
	import { onMount } from 'svelte';
	import { llmApi, type LLMProfileConfig, type ProviderInfo } from '$lib/api';
	import { loadSavedTargets, saveTargets, type SelectedTarget } from './planArchiveOperationsState.js';

	interface Props {
		selectedTargets?: SelectedTarget[];
		onchange?: (targets: SelectedTarget[]) => void;
	}

	let { selectedTargets = $bindable([]), onchange }: Props = $props();

	const FALLBACK_TARGETS: SelectedTarget[] = [
		{ provider: 'claude', model: 'claude-opus-4-5', profile_key: null },
		{ provider: 'gemini', model: 'gemini-2.0-flash', profile_key: null },
		{ provider: 'codex', model: 'gpt-5.5', profile_key: null },
	];

	let targets = $state<SelectedTarget[]>(FALLBACK_TARGETS);
	let loading = $state(false);
	let error = $state<string | null>(null);

	onMount(() => {
		const saved = loadSavedTargets();
		if (saved.length > 0) {
			selectedTargets = saved;
		}
		loadTargets();
	});

	async function loadTargets() {
		loading = true;
		error = null;
		try {
			const [providers, profiles] = await Promise.all([
				llmApi.getProviders(),
				llmApi.listProfiles()
			]);
			const nextTargets = buildTargets(providers, profiles.profiles);
			if (nextTargets.length > 0) {
				targets = nextTargets;
				const selectableKeys = new Set(nextTargets.map(targetKey));
				const nextSelected = selectedTargets.filter((t) => selectableKeys.has(targetKey(t)));
				if (nextSelected.length !== selectedTargets.length) {
					selectedTargets = nextSelected;
					saveTargets(nextSelected);
					onchange?.(nextSelected);
				}
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'profile 목록 로드 실패';
		} finally {
			loading = false;
		}
	}

	function buildTargets(providers: ProviderInfo[], profiles: LLMProfileConfig[]): SelectedTarget[] {
		const providerByKey = new Map(providers.map((p) => [p.key, p]));
		const enabledProfiles = profiles
			.filter((p) => p.enabled !== false)
			.sort((a, b) =>
				a.engine.localeCompare(b.engine) ||
				(a.priority ?? 0) - (b.priority ?? 0) ||
				a.name.localeCompare(b.name)
			);
		const profileTargets = enabledProfiles.map((profile) => {
			const provider = providerByKey.get(profile.engine);
			const model = provider?.default_model || provider?.models?.[0] || '';
			return {
				provider: profile.engine,
				model,
				profile_key: `${profile.engine}:${profile.name}`,
				engine: profile.engine,
				profile_name: profile.name,
				label: `${profile.engine}/${profile.name}/${model || 'default'}`
			};
		});
		const profiledEngines = new Set(profileTargets.map((t) => t.provider));
		const profilelessTargets = providers
			.filter((provider) => !profiledEngines.has(provider.key))
			.map((provider) => ({
				provider: provider.key,
				model: provider.default_model || provider.models?.[0] || '',
				profile_key: null,
				engine: null,
				profile_name: null,
				label: `${provider.key}/${provider.default_model || provider.models?.[0] || 'default'}`
			}));
		return [...profileTargets, ...profilelessTargets];
	}

	function isSelected(t: SelectedTarget): boolean {
		return selectedTargets.some((s) => targetKey(s) === targetKey(t));
	}

	function toggle(t: SelectedTarget) {
		let next: SelectedTarget[];
		if (isSelected(t)) {
			next = selectedTargets.filter((s) => targetKey(s) !== targetKey(t));
		} else {
			next = [...selectedTargets, t];
		}
		selectedTargets = next;
		saveTargets(next);
		onchange?.(next);
	}

	function targetLabel(t: SelectedTarget): string {
		if (t.label) return t.label;
		if (t.profile_name) return `${t.provider}/${t.profile_name}/${t.model || 'default'}`;
		return `${t.provider}/${t.model || 'default'}`;
	}

	function targetKey(t: SelectedTarget): string {
		return t.profile_key || `${t.provider}:${t.model}:profileless`;
	}
</script>

<div class="flex flex-wrap items-center gap-2">
	<span class="text-xs font-medium text-muted-foreground">분석 Target:</span>
	{#if loading}
		<span class="text-xs text-muted-foreground">profile 로드중...</span>
	{/if}
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
	{#if error}
		<span class="text-xs text-destructive" title={error}>profile 목록 로드 실패</span>
	{/if}
	{#if selectedTargets.length === 0}
		<span class="text-xs text-yellow-600">target을 1개 이상 선택하세요</span>
	{/if}
</div>
