<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		// Instagram 메뉴가 수집 관리로 통합됨 - 리다이렉트
		goto('/collect', { replaceState: true });
	});
</script>

<div class="flex justify-center items-center h-64">
	<div class="text-center">
		<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
		<p class="text-gray-500">수집 관리 페이지로 이동 중...</p>
	</div>
</div>
