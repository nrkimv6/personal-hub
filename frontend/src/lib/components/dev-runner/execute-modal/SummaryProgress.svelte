<script lang="ts">
	import { Check, ChevronDown, ChevronUp, FolderTree, GitBranch, RefreshCw, User, Loader2 } from 'lucide-svelte';

	interface ProgressValue {
		done: number;
		total: number;
	}

	interface Props {
		summaryKey: string;
		summary: string | null;
		summaryGenerating: boolean;
		summaryGenerated: boolean;
		progress: ProgressValue | null;
		worktreeBranch?: string | null;
		worktreePath?: string | null;
		worktreeOwner?: string | null;
		redisRunning: boolean;
		listenerRunning: boolean;
		onRegenerate: () => void | Promise<void>;
	}

	let {
		summaryKey,
		summary,
		summaryGenerating,
		summaryGenerated,
		progress,
		worktreeBranch = null,
		worktreePath = null,
		worktreeOwner = null,
		redisRunning,
		listenerRunning,
		onRegenerate
	}: Props = $props();

	let expanded = $state(false);

	$effect(() => {
		summaryKey;
		summary;
		expanded = false;
	});

	let progressPercent = $derived(progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0);
	let isComplete = $derived(!!progress && progress.total > 0 && progress.done === progress.total);
	let hasSummary = $derived(Boolean(summary && summary.trim()));
	let isLongSummary = $derived(Boolean(summary && summary.length > 200));
	let normalizedPath = $derived(
		worktreePath ? worktreePath.replace(/^.*?(\.worktrees[\\/].+)$/, '$1') : null
	);
	let normalizedOwner = $derived(
		worktreeOwner ? (worktreeOwner.split(/[\\/]/).pop() ?? worktreeOwner) : null
	);

	function handleRegenerate() {
		void onRegenerate();
	}
</script>

<div class="bg-muted border-b border-border px-5 py-4 space-y-4">
	<div class="space-y-2">
		<div class="flex items-center justify-between gap-2">
			<span class="text-xs font-medium text-muted-foreground uppercase tracking-wider">Summary</span>
			<button
				type="button"
				onclick={handleRegenerate}
				class="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
				disabled={summaryGenerating}
				title="요약 재생성"
			>
				{#if summaryGenerating}
					<Loader2 class="h-3 w-3 animate-spin" />
					<span>생성 중...</span>
				{:else if summaryGenerated}
					<Check class="h-3 w-3" />
					<span>완료</span>
				{:else}
					<RefreshCw class="h-3 w-3" />
					<span>재생성</span>
				{/if}
			</button>
		</div>

		{#if hasSummary}
			<div class="space-y-1">
				<p class={`text-sm leading-relaxed ${!expanded && isLongSummary ? 'line-clamp-3' : ''}`}>
					{summary}
				</p>
				{#if isLongSummary}
					<button
						type="button"
						onclick={() => { expanded = !expanded; }}
						class="inline-flex items-center gap-0.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
					>
						{#if expanded}
							<span>접기</span>
							<ChevronUp class="h-3 w-3" />
						{:else}
							<span>더보기</span>
							<ChevronDown class="h-3 w-3" />
						{/if}
					</button>
				{/if}
			</div>
		{:else}
			<div class="rounded-md border border-dashed border-border px-3 py-2">
				<p class="text-xs text-muted-foreground">요약 없음 - 재생성 버튼을 눌러 주세요</p>
			</div>
		{/if}
	</div>

	<div class="space-y-2">
		<div class="flex items-center justify-between gap-2">
			<span class="text-xs font-medium text-muted-foreground uppercase tracking-wider">Progress</span>
			<span class="text-xs font-mono text-muted-foreground">
				{progress ? `${progress.done}/${progress.total}` : '—'}
				{#if progress && progress.total > 0}
					<span class="ml-1.5 font-medium text-foreground">{progressPercent}%</span>
				{/if}
			</span>
		</div>

		{#if progress && progress.total > 0}
			<div class="h-1.5 overflow-hidden rounded bg-gray-200">
				<div
					class={`h-full rounded transition-all ${isComplete ? 'bg-success' : 'bg-primary'}`}
					style={`width: ${progressPercent}%`}
				></div>
			</div>
		{:else}
			<div class="rounded-md border border-dashed border-border px-3 py-2">
				<p class="text-xs text-muted-foreground">항목 없음</p>
			</div>
		{/if}
	</div>

	{#if normalizedPath || normalizedOwner || worktreeBranch}
		<div class="space-y-1.5 text-xs">
			{#if worktreeBranch}
				<div class="flex items-center gap-2">
					<GitBranch class="h-3 w-3 text-muted-foreground" />
					<span class="text-muted-foreground w-16 shrink-0">Branch</span>
					<span class="min-w-0 truncate font-mono text-foreground">{worktreeBranch}</span>
				</div>
			{/if}

			{#if normalizedPath}
				<div class="flex items-center gap-2">
					<FolderTree class="h-3 w-3 text-muted-foreground" />
					<span class="text-muted-foreground w-16 shrink-0">Worktree</span>
					<span class="min-w-0 truncate font-mono text-foreground">{normalizedPath}</span>
				</div>
			{/if}

			{#if normalizedOwner}
				<div class="flex items-center gap-2">
					<User class="h-3 w-3 text-muted-foreground" />
					<span class="text-muted-foreground w-16 shrink-0">Owner</span>
					<span class="min-w-0 truncate font-mono text-foreground">{normalizedOwner}</span>
				</div>
			{/if}
		</div>
	{/if}

	<div class="flex items-center gap-3 text-xs">
		<div class="flex items-center gap-1.5">
			<span class={`h-2 w-2 rounded-full ${redisRunning ? 'bg-success' : 'bg-gray-300'}`}></span>
			<span class="text-muted-foreground">Redis</span>
			<span class={redisRunning ? 'text-success' : 'text-destructive'}>
				{redisRunning ? '연결됨' : '끊김'}
			</span>
		</div>
		<div class="flex items-center gap-1.5">
			<span class={`h-2 w-2 rounded-full ${listenerRunning ? 'bg-success' : 'bg-gray-300'}`}></span>
			<span class="text-muted-foreground">Listener</span>
			<span class={listenerRunning ? 'text-success' : 'text-destructive'}>
				{listenerRunning ? '연결됨' : '끊김'}
			</span>
		</div>
	</div>
</div>
