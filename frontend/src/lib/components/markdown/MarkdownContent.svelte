<script lang="ts">
	import { renderMarkdown } from '../../../routes/notes/utils/markdown';
	import 'highlight.js/styles/github.css';

	interface Props {
		content: string;
		class?: string;
	}

	let { content, class: className = '' }: Props = $props();

	let html = $state('');

	$effect(() => {
		html = renderMarkdown(content ?? '');
	});
</script>

<div class="prose prose-sm max-w-none leading-relaxed {className}">
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html html}
</div>

