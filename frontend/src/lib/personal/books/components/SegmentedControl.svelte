<script lang="ts">
	let { value, options, onchange, class: className = '' } = $props<{
		value: string;
		options: { value: string; label: string }[];
		onchange: (value: string) => void;
		class?: string;
	}>();
</script>

<div class="inline-flex rounded-md border border-border bg-muted p-0.5 text-sm {className}">
	{#each options as option}
		<button
			type="button"
			onclick={() => onchange(option.value)}
			class="rounded-[5px] px-3 py-1 transition-colors {value === option.value ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
		>
			{option.label}
		</button>
	{/each}
</div>

