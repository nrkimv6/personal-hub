<script lang="ts">
	let { title, description = '' } = $props<{ title: string; description?: string }>();
</script>

<div class="rounded-lg border border-dashed border-border bg-card px-4 py-10 text-center">
	<p class="text-sm font-medium text-foreground">{title}</p>
	{#if description}
		<p class="mt-1 text-xs text-muted-foreground">{description}</p>
	{/if}
</div>

