<script lang="ts">
	import type { Book } from '../types';
	import AccessBadges from './AccessBadges.svelte';
	import CoverImage from './CoverImage.svelte';
	import StatusBadge from './StatusBadge.svelte';

	let { book } = $props<{ book: Book }>();
</script>

<a href="/personal/books/{book.id}" class="flex gap-3 rounded-lg border border-border bg-card p-3 transition-colors hover:bg-accent/60">
	<CoverImage title={book.title} src={book.cover} class="h-24 w-16 shrink-0" />
	<div class="min-w-0 flex-1">
		<h3 class="line-clamp-2 text-sm font-semibold leading-snug text-foreground">{book.title}</h3>
		<p class="mt-0.5 truncate text-xs text-muted-foreground">{book.author}</p>
		<div class="mt-2 flex flex-wrap items-center gap-1.5">
			<StatusBadge status={book.disposal} />
			{#if book.highlights.length > 0}
				<span class="text-[10px] text-muted-foreground">하이라이트 {book.highlights.length}</span>
			{/if}
			{#if book.reviewDate}
				<span class="text-[10px] text-muted-foreground">재검토 {book.reviewDate.slice(5)}</span>
			{/if}
		</div>
		<div class="mt-2">
			<AccessBadges library={book.library} millie={book.millie} ebook={book.ebook} used={book.usedBuyback} compact />
		</div>
	</div>
</a>

