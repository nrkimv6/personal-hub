<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/collect/rules', { replaceState: true });
	});
</script>

<div class="flex justify-center items-center h-64">
	<p class="text-gray-500">분류 규칙 페이지로 이동 중...</p>
</div>
