<script lang="ts">
	import MarkdownContent from '$lib/components/markdown/MarkdownContent.svelte';
	import type { FilePreviewResponse } from '$lib/types/fileSearch';
	import { Copy, ExternalLink, X } from 'lucide-svelte';

	interface Props {
		preview: FilePreviewResponse;
		raw: boolean;
		onClose: () => void;
		onToggleRaw: () => void;
		onOpenFile: () => void;
		onCopyPath: () => void;
	}

	let { preview, raw, onClose, onToggleRaw, onOpenFile, onCopyPath }: Props = $props();

	function handleBackdropClick(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			onClose();
		}
	}
</script>

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape') onClose();
	}}
/>

<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]"
	role="dialog"
	aria-modal="true"
	tabindex="-1"
	onclick={handleBackdropClick}
>
	<div class="flex max-h-[90vh] w-[min(1100px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
		<div class="flex flex-wrap items-start gap-3 border-b border-border px-4 py-3">
			<div class="min-w-0 flex-1">
				<div class="flex flex-wrap items-center gap-2">
					<h2 class="truncate text-base font-semibold text-foreground">{preview.file_name}</h2>
					<span class="rounded bg-muted px-2 py-0.5 text-[11px] font-medium text-foreground">
						{preview.extension ? preview.extension.toUpperCase() : 'TEXT'}
					</span>
					<span class="font-mono text-[11px] text-muted-foreground">{preview.encoding}</span>
				</div>
				<p class="mt-1 truncate font-mono text-[11px] text-muted-foreground">{preview.file_path}</p>
			</div>

			<div class="ml-auto flex shrink-0 flex-wrap items-center gap-2">
				{#if preview.extension === 'md'}
					<button
						type="button"
						onclick={onToggleRaw}
						class="rounded-md border border-border bg-background px-2.5 py-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
					>
						{raw ? 'Markdown 보기' : 'Raw 보기'}
					</button>
				{/if}
				<button
					type="button"
					onclick={onCopyPath}
					class="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
					title="full path 복사"
				>
					<Copy size={14} />
					경로 복사
				</button>
				<button
					type="button"
					onclick={onOpenFile}
					class="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
				>
					<ExternalLink size={14} />
					파일 열기
				</button>
				<button
					type="button"
					onclick={onClose}
					class="rounded-md border border-border bg-background p-1.5 text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
					aria-label="닫기"
				>
					<X size={16} />
				</button>
			</div>
		</div>

		<div class="min-h-0 flex-1 overflow-auto px-4 py-4">
			{#if preview.extension === 'md' && !raw}
				<MarkdownContent content={preview.content} class="min-h-full pb-8" />
			{:else}
				<pre class="whitespace-pre-wrap break-words rounded-xl bg-muted/30 p-4 font-mono text-xs text-foreground">{preview.content}</pre>
			{/if}
		</div>
	</div>
</div>
