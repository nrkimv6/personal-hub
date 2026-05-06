<script lang="ts">
	import { onMount } from 'svelte';
	import { ChevronDown, X, CheckCheck, XCircle } from 'lucide-svelte';
	import { llmApi, type LLMProfileConfig, type ProviderInfo } from '$lib/api';
	import {
		loadSavedTargets,
		saveTargets,
		targetKey,
		targetLabel,
		targetSelectionKey,
		type SelectedTarget,
	} from './planArchiveOperationsState.js';

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
	let open = $state(false);
	let providerModels = $state<Record<string, string[]>>({});

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
			providerModels = Object.fromEntries(providers.map((p) => [p.key, modelOptions(p)]));
			const nextTargets = buildTargets(providers, profiles.profiles);
			if (nextTargets.length > 0) {
				const selectedByKey = new Map(selectedTargets.map((t) => [targetSelectionKey(t), t]));
				const mergedTargets = nextTargets.map((t) => {
					const selected = selectedByKey.get(targetSelectionKey(t));
					return selected?.model ? withModel(t, selected.model) : t;
				});
				targets = mergedTargets;
				const selectableKeys = new Set(mergedTargets.map((t) => targetSelectionKey(t)));
				const nextSelected = selectedTargets.filter((t) => selectableKeys.has(targetSelectionKey(t)));
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

	function modelOptions(provider: ProviderInfo): string[] {
		const values = [provider.default_model, ...(provider.models || [])]
			.map((m) => (m || '').trim())
			.filter(Boolean);
		return Array.from(new Set(values));
	}

	function targetModelOptions(t: SelectedTarget): string[] {
		const options = providerModels[t.provider] ?? [];
		if (t.model && !options.includes(t.model)) return [t.model, ...options];
		return options;
	}

	function withModel(t: SelectedTarget, model: string): SelectedTarget {
		const next = { ...t, model: model || '' };
		return {
			...next,
			label: targetLabel(next)
		};
	}

	function buildTargets(providers: ProviderInfo[], profiles: LLMProfileConfig[]): SelectedTarget[] {
		const providerByKey = new Map(providers.map((p) => [p.key, p]));
		const enabledProfiles = (profiles || [])
			.filter((p) => p.enabled !== false)
			.sort((a, b) =>
				a.engine.localeCompare(b.engine) ||
				(a.priority ?? 0) - (b.priority ?? 0) ||
				a.name.localeCompare(b.name)
		);
		const profileTargets: SelectedTarget[] = enabledProfiles.map((profile) => {
			const provider = providerByKey.get(profile.engine);
			const model = provider ? (modelOptions(provider)[0] || '') : '';
			return {
				provider: profile.engine,
				model,
				profile_key: `${profile.engine}:${profile.name}`,
				engine: profile.engine,
				profile_name: profile.name,
				label: `${profile.engine}/${profile.name}/${model || 'default'}`,
				kind: 'profile'
			};
		});
		const engineTargets: SelectedTarget[] = (providers || []).map((provider) => ({
			provider: provider.key,
			model: modelOptions(provider)[0] || '',
			profile_key: null,
			engine: null,
			profile_name: null,
			label: `${provider.key}/${modelOptions(provider)[0] || 'default'}`,
			kind: 'engine'
		}));
		const all = [...profileTargets, ...engineTargets];
		// De-dupe by normalized key (profile_key/engine+profile/provider+model).
		const seen = new Set<string>();
		const out: SelectedTarget[] = [];
		for (const t of all) {
			const k = targetKey(t);
			if (seen.has(k)) continue;
			seen.add(k);
			out.push(t);
		}
		return out;
	}

	function isSelected(t: SelectedTarget): boolean {
		return selectedTargets.some((s) => targetSelectionKey(s) === targetSelectionKey(t));
	}

	function toggle(t: SelectedTarget) {
		let next: SelectedTarget[];
		if (isSelected(t)) {
			next = selectedTargets.filter((s) => targetSelectionKey(s) !== targetSelectionKey(t));
		} else {
			next = [...selectedTargets, t];
		}
		selectedTargets = next;
		saveTargets(next);
		onchange?.(next);
	}

	function changeTargetModel(t: SelectedTarget, model: string) {
		const nextTarget = withModel(t, model);
		targets = targets.map((row) => targetSelectionKey(row) === targetSelectionKey(t) ? nextTarget : row);
		if (isSelected(t)) {
			selectedTargets = selectedTargets.map((row) => targetSelectionKey(row) === targetSelectionKey(t) ? withModel(row, model) : row);
			saveTargets(selectedTargets);
			onchange?.(selectedTargets);
		}
	}

	function removeTarget(t: SelectedTarget) {
		selectedTargets = selectedTargets.filter((s) => targetSelectionKey(s) !== targetSelectionKey(t));
		saveTargets(selectedTargets);
		onchange?.(selectedTargets);
	}

	function selectAll() {
		selectedTargets = [...targets];
		saveTargets(selectedTargets);
		onchange?.(selectedTargets);
	}

	function clearAll() {
		selectedTargets = [];
		saveTargets([]);
		onchange?.([]);
	}

	function groupKeys(): string[] {
		const keys = new Set<string>();
		for (const t of targets) keys.add(t.provider);
		return Array.from(keys).sort();
	}

	function groupTargets(provider: string): SelectedTarget[] {
		const group = targets.filter((t) => t.provider === provider);
		// engine first, then profiles by name/model
		return group.sort((a, b) => {
			const ak = a.kind === 'engine' ? 0 : 1;
			const bk = b.kind === 'engine' ? 0 : 1;
			if (ak !== bk) return ak - bk;
			return targetLabel(a).localeCompare(targetLabel(b));
		});
	}
</script>

<div class="flex flex-col gap-2">
	<div class="flex flex-wrap items-center gap-2">
		<span class="text-xs font-medium text-muted-foreground">분석 Target:</span>
		<button
			type="button"
			class="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-muted"
			aria-expanded={open}
			onclick={() => { open = !open; }}
		>
			<span>{selectedTargets.length}개 선택됨</span>
			<ChevronDown class="h-3 w-3 {open ? 'rotate-180' : ''}" />
		</button>
		{#if loading}
			<span class="text-xs text-muted-foreground">profile 로드중...</span>
		{/if}
		{#if error}
			<span class="text-xs text-destructive" title={error}>profile 목록 로드 실패</span>
		{/if}
		{#if selectedTargets.length === 0}
			<span class="text-xs text-yellow-600">target을 1개 이상 선택하세요</span>
		{/if}
		<div class="ml-auto flex items-center gap-1">
			<button
				type="button"
				class="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-muted"
				onclick={selectAll}
				disabled={targets.length === 0}
				title="전체 선택"
			>
				<CheckCheck class="h-3 w-3" />전체
			</button>
			<button
				type="button"
				class="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs hover:bg-muted"
				onclick={clearAll}
				disabled={selectedTargets.length === 0}
				title="전체 해제"
			>
				<XCircle class="h-3 w-3" />해제
			</button>
		</div>
	</div>

	{#if selectedTargets.length > 0}
		<div class="flex flex-wrap gap-1">
			{#each selectedTargets as t}
				<button
					type="button"
					class="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs hover:bg-muted"
					title={targetLabel(t)}
					onclick={() => removeTarget(t)}
				>
					<span class="max-w-[320px] truncate">{targetLabel(t)}</span>
					<X class="h-3 w-3 opacity-60" />
				</button>
			{/each}
		</div>
	{/if}

	{#if open}
		<div class="rounded border border-border p-2">
			<div class="grid grid-cols-1 gap-2 lg:grid-cols-2">
				{#each groupKeys() as k}
					<div class="rounded border border-border/60 p-2">
						<div class="mb-1 text-xs font-medium text-muted-foreground">{k}</div>
						<div class="flex flex-wrap gap-1">
							{#each groupTargets(k) as t}
								{@const checked = isSelected(t)}
								{@const modelChoices = targetModelOptions(t)}
								<div class="inline-flex items-center overflow-hidden rounded border text-xs {checked ? 'border-primary bg-primary/10' : 'border-border'}">
									<button
										type="button"
										class="px-2 py-1 hover:bg-muted"
										aria-pressed={checked}
										title={targetLabel(t)}
										onclick={() => toggle(t)}
									>
										{targetLabel(t)}
									</button>
									{#if modelChoices.length > 1}
										<select
											class="border-l border-border bg-background px-1 py-1 text-xs"
											aria-label="{targetLabel(t)} model"
											value={t.model}
											onclick={(event) => event.stopPropagation()}
											onchange={(event) => changeTargetModel(t, (event.currentTarget as HTMLSelectElement).value)}
										>
											{#each modelChoices as model}
												<option value={model}>{model}</option>
											{/each}
										</select>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
