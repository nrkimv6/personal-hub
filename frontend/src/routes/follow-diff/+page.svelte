<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/collect/follow-diff', { replaceState: true });
	});
</script>

<div></div>
