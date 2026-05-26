<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';

	function normalizeView(tab: string | null): string {
		if (tab === 'history' || tab === 'cancellation-history') return tab;
		return 'schedules';
	}

	function targetHref() {
		const target = new URL('/monitoring', $page.url.origin);
		target.searchParams.set('type', 'coupang');
		target.searchParams.set('view', normalizeView($page.url.searchParams.get('tab')));
		const id = $page.url.searchParams.get('id');
		if (id) target.searchParams.set('id', id);
		return `${target.pathname}${target.search}`;
	}

	onMount(() => {
		goto(targetHref(), { replaceState: true });
	});
</script>

<svelte:head>
	<meta http-equiv="refresh" content="0; url=/monitoring?type=coupang&view=schedules" />
</svelte:head>
