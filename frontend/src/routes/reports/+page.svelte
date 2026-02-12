<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	onMount(() => goto('/writing?tab=reports', { replaceState: true }));
</script>
