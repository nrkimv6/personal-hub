<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	onMount(() => goto('/automation?tab=sleep-now', { replaceState: true }));
</script>
