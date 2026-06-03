<script lang="ts">
	let { active = false, count = undefined, onclick, children } = $props<{
		active?: boolean;
		count?: number;
		onclick?: () => void;
		children: import('svelte').Snippet;
	}>();
</script>

<button
	type="button"
	{onclick}
	class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors {active ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-card text-foreground hover:bg-accent'}"
>
	{@render children()}
	{#if typeof count === 'number'}
		<span class="rounded-full px-1.5 text-[10px] {active ? 'bg-primary-foreground/20' : 'bg-muted text-muted-foreground'}">{count}</span>
	{/if}
</button>

