<script lang="ts">
	import type { Preset } from '$lib/types/fileSearch';

	interface Props {
		presets: Preset[];
		selectedPresetId: string | null;
		onselect: (preset: Preset | null) => void;
	}

	let { presets, selectedPresetId, onselect }: Props = $props();
</script>

<div class="flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
	{#each presets as preset}
		<button
			onclick={() => onselect(selectedPresetId === preset.id ? null : preset)}
			class="shrink-0 flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium
				   transition-all
				   {selectedPresetId === preset.id
				? 'border-primary bg-primary text-primary-foreground shadow-sm'
				: 'border-border bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground'}"
		>
			<span>{preset.name}</span>
		</button>
	{/each}
</div>
