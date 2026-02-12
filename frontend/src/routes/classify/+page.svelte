<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => {
		// 루트 경로 접근 시 대시보드로 리다이렉트
		goto('/classify/dashboard', { replaceState: true });
	});
</script>

<div class="flex items-center justify-center h-full">
	<div class="text-center">
		<div class="animate-spin text-6xl mb-4">⏳</div>
		<p class="text-gray-600">대시보드로 이동 중...</p>
	</div>
</div>
