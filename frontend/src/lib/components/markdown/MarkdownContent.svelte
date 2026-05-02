<script lang="ts">
	import { renderMarkdown } from '../../../routes/notes/utils/markdown';
	import { variantClasses, type MarkdownContentVariant } from './markdownVariants';
	import 'highlight.js/styles/github.css';

	interface Props {
		content: string;
		class?: string;
		style?: string;
		/** density variant — add prose classes via this prop only, not via class="" directly */
		variant?: MarkdownContentVariant;
	}

	let { content, class: className = '', style, variant = 'default' }: Props = $props();

	let html = $state('');

	$effect(() => {
		html = renderMarkdown(content ?? '');
	});
</script>

<div class="{variantClasses[variant]} {className}" {style}>
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html html}
</div>
