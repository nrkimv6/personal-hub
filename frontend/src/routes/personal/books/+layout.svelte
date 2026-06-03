<script lang="ts">
	import { onMount } from 'svelte';
	import BookShell from '$lib/personal/books/components/BookShell.svelte';
	import { booksState } from '$lib/personal/books/state/books.svelte';

	let { children } = $props<{ children: import('svelte').Snippet }>();

	onMount(() => {
		booksState.load();
	});
</script>

<BookShell>
	{@render children()}
</BookShell>

