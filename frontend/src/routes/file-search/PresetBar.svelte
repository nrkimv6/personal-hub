<script lang="ts">
	import type { Preset } from '$lib/types/fileSearch';

	interface Props {
		presets: Preset[];
		selectedPresetId: string | null;
		onselect: (preset: Preset | null) => void;
	}

	let { presets, selectedPresetId, onselect }: Props = $props();
</script>

<div class="flex flex-wrap gap-2">
	{#each presets as preset}
		<button
			onclick={() => onselect(selectedPresetId === preset.id ? null : preset)}
			class="flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium
				   transition-all
				   {selectedPresetId === preset.id
				? 'border-primary bg-primary text-primary-foreground shadow-sm'
				: 'border-border bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground'}"
		>
			<span>{preset.icon}</span>
			<span>{preset.name}</span>
		</button>
	{/each}
</div>
