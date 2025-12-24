<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		// 업체 관리 페이지로 리다이렉트 (슬롯 조회는 업체 관리에서 모달로 제공)
		goto('/businesses', { replaceState: true });
	});
</script>

<div class="flex justify-center items-center h-64">
	<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
</div>
