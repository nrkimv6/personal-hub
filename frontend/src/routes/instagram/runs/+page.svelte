<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/collect/history', { replaceState: true });
	});
</script>

<div class="flex justify-center items-center h-64">
	<p class="text-muted-foreground">크롤링 이력 페이지로 이동 중...</p>
</div>
