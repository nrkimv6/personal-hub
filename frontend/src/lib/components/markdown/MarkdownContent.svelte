<script lang="ts">
	import { renderMarkdown } from '../../../routes/notes/utils/markdown';
	import 'highlight.js/styles/github.css';

	interface Props {
		content: string;
		class?: string;
		style?: string;
		/** density variant — add prose classes via this prop only, not via class="" directly */
		variant?: 'compact' | 'default' | 'document';
	}

	let { content, class: className = '', style, variant = 'default' }: Props = $props();

	const variantClasses: Record<NonNullable<Props['variant']>, string> = {
		compact: 'prose prose-sm dark:prose-invert max-w-none text-sm leading-snug',
		default: 'prose prose-sm dark:prose-invert max-w-none leading-relaxed',
		document: 'prose dark:prose-invert max-w-prose leading-relaxed mx-auto'
	};

	let html = $state('');

	$effect(() => {
		html = renderMarkdown(content ?? '');
	});
</script>

<div class="{variantClasses[variant]} {className}" {style}>
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html html}
</div>
