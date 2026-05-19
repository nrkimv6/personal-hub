<script lang="ts">
	import type { ProviderInfo } from '$lib/api';
	import type { LlmCreateForm } from '../types';

	interface Props {
		createForm: LlmCreateForm;
		providers: ProviderInfo[];
		providersLoading: boolean;
		providersError: string | null;
		getProviderModels: (providerKey: string) => string[];
	}

	let {
		createForm = $bindable(),
		providers,
		providersLoading,
		providersError,
		getProviderModels
	}: Props = $props();
</script>

<div class="grid grid-cols-2 gap-4">
	<div>
		<label class="block text-sm font-medium text-foreground mb-1">Provider</label>
		{#if providersError}
			<p class="text-sm text-red-500">{providersError}</p>
		{:else if providersLoading}
			<p class="text-sm text-muted-foreground">로딩 중...</p>
		{:else}
			<select bind:value={createForm.provider} class="w-full px-3 py-2 border border-border rounded-lg">
				{#each providers as provider}
					<option value={provider.key}>{provider.display_name}</option>
				{/each}
			</select>
		{/if}
	</div>
	<div>
		<label class="block text-sm font-medium text-foreground mb-1">Model</label>
		<select bind:value={createForm.model} class="w-full px-3 py-2 border border-border rounded-lg">
			{#each getProviderModels(createForm.provider) as modelOption}
				<option value={modelOption === '(기본)' ? '' : modelOption}>
					{modelOption}
				</option>
			{/each}
		</select>
	</div>
</div>
