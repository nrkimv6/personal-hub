<script lang="ts">
	import AccessBadges from '$lib/personal/books/components/AccessBadges.svelte';
	import CoverImage from '$lib/personal/books/components/CoverImage.svelte';
	import StatusBadge from '$lib/personal/books/components/StatusBadge.svelte';
	import { sampleBooks } from '$lib/personal/books/sample-data';
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-xl font-semibold md:text-2xl">서재 스타일가이드</h1>
		<p class="mt-0.5 text-xs text-muted-foreground">book-whisperer 이식 컴포넌트의 visual QA surface입니다.</p>
	</div>

	<section class="space-y-3 rounded-lg border border-border bg-card p-4">
		<h2 class="text-sm font-semibold">Status</h2>
		<div class="flex flex-wrap gap-2">
			<StatusBadge status="undecided" />
			<StatusBadge status="keep" />
			<StatusBadge status="sell" />
			<StatusBadge status="scan" />
			<StatusBadge status="discard" />
			<StatusBadge status="review" />
		</div>
	</section>

	<section class="space-y-3 rounded-lg border border-border bg-card p-4">
		<h2 class="text-sm font-semibold">Access</h2>
		<AccessBadges library="yes" millie="check" ebook="yes" used="no" size="md" />
	</section>

	<section class="space-y-3 rounded-lg border border-border bg-card p-4">
		<h2 class="text-sm font-semibold">Cover</h2>
		<div class="flex gap-3">
			{#each sampleBooks.slice(0, 4) as book}
				<CoverImage title={book.title} class="h-28 w-20" />
			{/each}
		</div>
	</section>
</div>

