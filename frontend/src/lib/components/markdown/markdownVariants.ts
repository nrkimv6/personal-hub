export type MarkdownContentVariant = 'compact' | 'default' | 'document' | 'filePreview' | 'plan';

export const variantClasses: Record<MarkdownContentVariant, string> = {
	compact: [
		'prose prose-sm max-w-none text-sm leading-snug text-foreground',
		'prose-headings:text-foreground prose-p:text-foreground prose-li:text-foreground prose-strong:text-foreground',
		'prose-a:break-words prose-a:text-primary',
		'prose-blockquote:my-2 prose-blockquote:border-l-2 prose-blockquote:border-primary/35 prose-blockquote:bg-muted/35 prose-blockquote:px-2.5 prose-blockquote:py-1.5 prose-blockquote:text-muted-foreground',
		'prose-code:break-words prose-code:text-[12px] prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none',
		'prose-pre:my-2 prose-pre:max-w-full prose-pre:overflow-x-auto prose-pre:rounded-md prose-pre:bg-muted prose-pre:p-2.5 prose-pre:text-xs prose-pre:text-foreground',
		'prose-table:my-2 prose-table:text-xs prose-th:px-2 prose-th:py-1 prose-th:text-foreground prose-td:px-2 prose-td:py-1 prose-td:text-foreground'
	].join(' '),
	default: 'prose prose-sm dark:prose-invert max-w-none leading-relaxed',
	document: 'prose dark:prose-invert max-w-prose leading-relaxed mx-auto',
	filePreview: [
		'prose prose-sm mx-auto w-full max-w-[78ch] leading-[1.65] text-foreground',
		'prose-headings:font-semibold prose-headings:tracking-normal prose-headings:text-foreground',
		'prose-h1:mt-0 prose-h1:mb-4 prose-h1:text-xl prose-h1:leading-snug',
		'prose-h2:mt-6 prose-h2:mb-3 prose-h2:border-b prose-h2:border-border prose-h2:pb-1.5 prose-h2:text-lg',
		'prose-h3:mt-5 prose-h3:mb-2 prose-h3:text-base',
		'prose-p:my-3 prose-p:text-foreground prose-ul:my-3 prose-ol:my-3 prose-li:my-1 prose-li:text-foreground',
		'prose-strong:text-foreground prose-a:break-words prose-a:text-primary',
		'prose-blockquote:my-4 prose-blockquote:border-l-2 prose-blockquote:border-primary/40 prose-blockquote:bg-muted/40 prose-blockquote:px-4 prose-blockquote:py-2.5 prose-blockquote:text-sm prose-blockquote:font-normal prose-blockquote:not-italic prose-blockquote:text-muted-foreground',
		'prose-code:break-words prose-code:text-[12.5px] prose-code:font-medium prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none',
		'prose-pre:my-4 prose-pre:max-w-full prose-pre:overflow-x-auto prose-pre:rounded-lg prose-pre:bg-muted prose-pre:p-4 prose-pre:text-xs prose-pre:text-foreground',
		'prose-table:my-4 prose-table:text-xs prose-th:px-2.5 prose-th:py-1.5 prose-th:text-foreground prose-td:px-2.5 prose-td:py-1.5 prose-td:text-foreground'
	].join(' '),
	plan: [
		'prose prose-sm max-w-none text-[13px] leading-[1.55] text-foreground',
		'prose-headings:font-semibold prose-headings:tracking-normal prose-headings:text-foreground',
		'prose-h1:mt-0 prose-h1:mb-3 prose-h1:text-lg prose-h1:leading-snug',
		'prose-h2:mt-5 prose-h2:mb-2 prose-h2:border-b prose-h2:border-border prose-h2:pb-1 prose-h2:text-base',
		'prose-h3:mt-4 prose-h3:mb-1.5 prose-h3:text-sm',
		'prose-p:my-2 prose-p:text-foreground prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-li:text-foreground',
		'prose-strong:text-foreground prose-a:break-words prose-a:text-primary',
		'prose-blockquote:my-3 prose-blockquote:border-l-2 prose-blockquote:border-primary/40 prose-blockquote:bg-muted/40 prose-blockquote:px-3 prose-blockquote:py-2 prose-blockquote:text-[12.5px] prose-blockquote:font-normal prose-blockquote:not-italic prose-blockquote:text-muted-foreground',
		'prose-code:break-words prose-code:text-[12px] prose-code:font-medium prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none',
		'prose-pre:my-3 prose-pre:max-w-full prose-pre:overflow-x-auto prose-pre:rounded-md prose-pre:bg-muted prose-pre:p-3 prose-pre:text-xs prose-pre:text-foreground',
		'prose-table:text-xs prose-th:px-2 prose-th:py-1 prose-th:text-foreground prose-td:px-2 prose-td:py-1 prose-td:text-foreground'
	].join(' ')
};
