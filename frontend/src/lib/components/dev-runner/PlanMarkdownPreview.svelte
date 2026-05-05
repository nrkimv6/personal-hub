<script lang="ts">
	import { ExternalLink, Loader2, RefreshCw, X } from 'lucide-svelte';
	import { devRunnerPlanApi } from '$lib/api/dev-runner';
	import MarkdownContent from '$lib/components/markdown/MarkdownContent.svelte';
	import { encodePathToBase64 } from '$lib/utils/encoding';

	interface Props {
		planPath: string;
		title?: string | null;
		onClose?: () => void;
	}

	let { planPath, title = null, onClose }: Props = $props();

	let content = $state('');
	let resolvedPath = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);
	let loadVersion = 0;

	let filename = $derived(title || resolvedPath.split(/[\\/]/).pop() || planPath.split(/[\\/]/).pop() || 'Plan');

	async function loadContent(path: string) {
		if (!path) return;
		const requestVersion = ++loadVersion;
		loading = true;
		error = null;
		content = '';
		resolvedPath = path;
		try {
			const encoded = encodePathToBase64(path);
			const response = await devRunnerPlanApi.content(encoded);
			if (requestVersion !== loadVersion) return;
			content = response.content ?? '';
			resolvedPath = response.path || path;
		} catch (e) {
			if (requestVersion !== loadVersion) return;
			error = e instanceof Error ? e.message : '내용을 불러오지 못했습니다.';
		} finally {
			if (requestVersion === loadVersion) {
				loading = false;
			}
		}
	}

	function openInPlanManager() {
		window.open('/plans', '_blank', 'noopener,noreferrer');
	}

	$effect(() => {
		if (planPath) {
			void loadContent(planPath);
		}
	});
</script>

<section class="flex h-full min-h-0 flex-col overflow-hidden bg-card text-card-foreground sm:rounded-md sm:border sm:border-border sm:shadow-sm">
	<header class="sticky top-0 z-10 flex shrink-0 items-center gap-2 border-b border-border bg-card/95 px-3 py-2 backdrop-blur">
		<div class="min-w-0 flex-1">
			<div class="truncate text-xs font-semibold text-foreground" title={filename}>{filename}</div>
			<div class="truncate font-mono text-[10px] text-muted-foreground" title={resolvedPath || planPath}>{resolvedPath || planPath}</div>
		</div>
		<button
			type="button"
			class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
			onclick={() => loadContent(planPath)}
			disabled={loading}
			title="새로고침"
			aria-label="계획서 전문 새로고침"
		>
			{#if loading}
				<Loader2 class="h-4 w-4 animate-spin" />
			{:else}
				<RefreshCw class="h-4 w-4" />
			{/if}
		</button>
		<button
			type="button"
			class="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground sm:inline-flex"
			onclick={openInPlanManager}
			title="계획서 관리에서 열기"
			aria-label="계획서 관리에서 열기"
		>
			<ExternalLink class="h-4 w-4" />
		</button>
		<button
			type="button"
			class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
			onclick={() => onClose?.()}
			title="닫기"
			aria-label="계획서 전문 닫기"
		>
			<X class="h-4 w-4" />
		</button>
	</header>

	<div class="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-3 py-3 dr-scrollbar-thin">
		{#if loading}
			<div class="flex h-full min-h-[12rem] items-center justify-center text-xs text-muted-foreground">
				<Loader2 class="mr-2 h-4 w-4 animate-spin" />
				불러오는 중...
			</div>
		{:else if error}
			<div class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">
				{error}
			</div>
		{:else if !content.trim()}
			<div class="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
				표시할 Markdown 내용이 없습니다.
			</div>
		{:else}
			<MarkdownContent content={content} variant="plan" class="min-w-0 max-w-full pb-8" />
		{/if}
	</div>
</section>
