<script lang="ts">
	import { Pencil } from 'lucide-svelte';
	import { quickMemo, openQuickMemo, detectCurrentMenu } from '$lib/stores/quickMemo';

	function handleClick() {
		if ($quickMemo.open) return;
		const menuInfo = detectCurrentMenu(window.location.pathname);
		const tab = new URLSearchParams(window.location.search).get('tab');
		openQuickMemo(menuInfo?.menuId ?? null, menuInfo?.label ?? null, tab);
	}
</script>

{#if !$quickMemo.open}
	<button
		onclick={handleClick}
		class="fixed bottom-20 right-4 w-14 h-14 rounded-full bg-primary text-primary-foreground shadow-lg flex items-center justify-center hover:scale-105 transition-transform lg:hidden z-30"
		aria-label="빠른 메모 작성"
	>
		<Pencil size={22} />
	</button>
{/if}
