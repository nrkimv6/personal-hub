<script lang="ts">
	import { booksState } from '../state/books.svelte';
</script>

{#if booksState.pendingUndo}
	<div class="fixed bottom-20 left-1/2 z-50 flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3 text-sm shadow-lg md:bottom-5">
		<span class="min-w-0 truncate text-foreground">{booksState.pendingUndo.message}</span>
		<div class="flex shrink-0 items-center gap-2">
			<button type="button" class="text-primary hover:underline" onclick={() => booksState.undo()}>되돌리기</button>
			<button type="button" class="text-muted-foreground hover:text-foreground" onclick={() => booksState.clearUndo()}>닫기</button>
		</div>
	</div>
{/if}

