<script lang="ts">
	import EmptyState from '$lib/personal/books/components/EmptyState.svelte';
	import SegmentedControl from '$lib/personal/books/components/SegmentedControl.svelte';
	import { booksState } from '$lib/personal/books/state/books.svelte';

	type GroupBy = 'book' | 'tag' | 'importance';
	let groupBy = $state<GroupBy>('book');

	const items = $derived(booksState.books.flatMap((book) => book.highlights.map((highlight) => ({ ...highlight, book }))));
	const sorted = $derived(
		items.slice().sort((a, b) => {
			if (groupBy === 'importance') return b.importance - a.importance;
			if (groupBy === 'tag') return (a.tags[0] ?? '').localeCompare(b.tags[0] ?? '');
			return a.book.title.localeCompare(b.book.title);
		})
	);
</script>

<div class="space-y-4">
	<div class="flex flex-wrap items-end justify-between gap-3">
		<div>
			<h1 class="text-xl font-semibold md:text-2xl">하이라이트</h1>
			<p class="mt-0.5 text-xs text-muted-foreground">총 {items.length}개의 문장</p>
		</div>
		<SegmentedControl value={groupBy} onchange={(value) => (groupBy = value as GroupBy)} options={[{ value: 'book', label: '책별' }, { value: 'tag', label: '태그별' }, { value: 'importance', label: '중요도순' }]} />
	</div>

	{#if items.length === 0}
		<EmptyState title="아직 하이라이트가 없습니다" />
	{:else}
		<div class="grid gap-3 md:grid-cols-2">
			{#each sorted as highlight}
				<article class="space-y-2 rounded-lg border border-border bg-card p-4">
					<blockquote class="text-sm leading-relaxed text-foreground">"{highlight.quote}"</blockquote>
					{#if highlight.memo}<p class="text-xs text-muted-foreground">{highlight.memo}</p>{/if}
					<div class="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
						<a href="/personal/books/{highlight.book.id}" class="font-medium text-foreground hover:underline">{highlight.book.title}</a>
						<span>p.{highlight.page}</span><span>중요도 {highlight.importance}</span>
						{#each highlight.tags as tag}<span class="rounded-full bg-muted px-2 py-0.5">#{tag}</span>{/each}
					</div>
				</article>
			{/each}
		</div>
	{/if}
</div>

