<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	onMount(() => goto('/collect/google?tab=results', { replaceState: true }));
</script>
