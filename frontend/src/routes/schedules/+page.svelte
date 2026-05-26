<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';

	onMount(() => {
		const tab = $page.url.searchParams.get('tab');
		const target = new URL('/monitoring', $page.url.origin);
		for (const [key, value] of $page.url.searchParams) {
			if (key !== 'tab') {
				target.searchParams.append(key, value);
			}
		}
		target.searchParams.set('type', 'naver');
		target.searchParams.set('view', 'schedules');
		if (tab) {
			target.searchParams.set('sub', tab);
		}
		goto(`${target.pathname}${target.search}`, { replaceState: true });
	});
</script>

<div class="flex h-64 items-center justify-center">
	<div class="h-12 w-12 animate-spin rounded-full border-b-2 border-blue-600"></div>
</div>
