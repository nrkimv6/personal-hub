<script lang="ts">
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import EncodingFixer from './EncodingFixer.svelte';
</script>

<PageHeader title="유틸리티" subtitle="개발 편의 도구 모음" />

<div class="p-4 lg:p-6 space-y-6">
	<EncodingFixer />
</div>
