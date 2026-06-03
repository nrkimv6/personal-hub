<script lang="ts">
	let { title, src = null, class: className = '' } = $props<{
		title: string;
		src?: string | null;
		class?: string;
	}>();

	const fallback = $derived(title.replace(/\s+/g, '').slice(0, 2) || '책');
</script>

{#if src}
	<img src={src} alt="{title} 표지" class="rounded-md object-cover shadow-sm {className}" />
{:else}
	<div class="book-cover flex items-center justify-center rounded-md text-sm font-semibold shadow-sm {className}" aria-label="{title} 표지 대체 이미지">
		{fallback}
	</div>
{/if}

