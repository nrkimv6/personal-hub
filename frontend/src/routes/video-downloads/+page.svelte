<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	onMount(() => goto('/collect?tab=videos', { replaceState: true }));
</script>
