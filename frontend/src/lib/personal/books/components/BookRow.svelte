<script lang="ts">
	import type { Book } from '../types';
	import CoverImage from './CoverImage.svelte';
	import StatusBadge from './StatusBadge.svelte';

	let { book } = $props<{ book: Book }>();
</script>

<a
	href="/personal/books/{book.id}"
	class="grid grid-cols-[40px_minmax(0,3fr)_minmax(0,1.4fr)_120px_140px_110px_120px_80px] items-center gap-3 border-b border-border px-3 py-2 text-sm hover:bg-accent/50"
>
	<CoverImage title={book.title} src={book.cover} class="h-10 w-8" />
	<div class="min-w-0">
		<div class="truncate font-medium text-foreground">{book.title}</div>
		<div class="truncate text-xs text-muted-foreground">{book.publisher} · {book.publishedYear ?? '-'}</div>
	</div>
	<div class="truncate text-muted-foreground">{book.author}</div>
	<StatusBadge status={book.disposal} />
	<StatusBadge status={book.recommendation} prefix="추천:" />
	<span class="text-xs text-muted-foreground">{book.reviewDate ?? '-'}</span>
	<span class="truncate text-xs text-muted-foreground">{book.location}</span>
	<span class="text-right text-xs text-muted-foreground">{book.highlights.length}</span>
</a>

