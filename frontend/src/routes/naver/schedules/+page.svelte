<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';

	const DEFAULT_HREF = '/monitoring?type=naver&view=schedules';

	function normalizeSub(tab: string | null): string | null {
		if (tab === 'booking' || tab === 'recurring' || tab === 'popup_monitor' || tab === 'history' || tab === 'businesses') {
			return tab;
		}
		return null;
	}

	function targetHref() {
		const target = new URL('/monitoring', $page.url.origin);
		target.search = new URL(DEFAULT_HREF, $page.url.origin).search;
		const sub = normalizeSub($page.url.searchParams.get('tab'));
		const id = $page.url.searchParams.get('id');
		if (sub) target.searchParams.set('sub', sub);
		if (id) target.searchParams.set('id', id);
		return `${target.pathname}${target.search}`;
	}

	onMount(() => {
		goto(targetHref(), { replaceState: true });
	});
</script>
