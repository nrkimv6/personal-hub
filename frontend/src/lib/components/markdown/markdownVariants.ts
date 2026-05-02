export type MarkdownContentVariant = 'compact' | 'default' | 'document';

export const variantClasses: Record<MarkdownContentVariant, string> = {
	compact: 'prose prose-sm dark:prose-invert max-w-none text-sm leading-snug',
	default: 'prose prose-sm dark:prose-invert max-w-none leading-relaxed',
	document: 'prose dark:prose-invert max-w-prose leading-relaxed mx-auto'
};
