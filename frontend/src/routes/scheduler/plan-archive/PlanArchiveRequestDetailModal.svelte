<script lang="ts">
	import { X, Copy, ChevronDown, ChevronRight } from 'lucide-svelte';
	import type { ArchiveLLMRequestDetail, ArchiveRelatedRecord } from '$lib/api/plan-records';

	interface Props {
		request: ArchiveLLMRequestDetail | null;
		onclose?: () => void;
	}

	let { request, onclose }: Props = $props();

	let showRaw = $state(false);
	let showPrompt = $state(false);
	let showRecord = $state(false);
	let showAudit = $state(false);
	let copiedField = $state<string | null>(null);

	async function copy(field: string, text: string | null) {
		if (!text) return;
		await navigator.clipboard.writeText(text).catch(() => {});
		copiedField = field;
		setTimeout(() => { copiedField = null; }, 1500);
	}

	function parseJson(s: string | null): unknown {
		if (!s) return null;
		try { return JSON.parse(s); } catch { return null; }
	}

	function targetText(req: ArchiveLLMRequestDetail): string {
		if (req.target_label) return req.target_label;
		const model = req.model || 'default';
		if (req.engine && req.profile_name) return `${req.engine}/${req.profile_name}/${model}`;
		return `${req.provider}/${model}`;
	}

	const parsedResult = $derived(parseJson(request?.result ?? null));
</script>

{#if request}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
		role="dialog"
		aria-modal="true"
	>
		<div class="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg bg-background shadow-xl">
			<!-- Header -->
			<div class="flex items-center justify-between border-b border-border px-4 py-3">
				<h3 class="text-sm font-semibold">LLM Request 상세 #{request.id}</h3>
				<button class="rounded p-1 hover:bg-muted" onclick={onclose}>
					<X class="h-4 w-4" />
				</button>
			</div>

			<div class="overflow-y-auto p-4 space-y-4 text-sm">
				<!-- Meta -->
				<div class="grid grid-cols-2 gap-2 rounded bg-muted/40 p-3 text-xs">
					<div><span class="text-muted-foreground">상태</span> <span class="font-medium">{request.status}</span></div>
					<div><span class="text-muted-foreground">target</span> <span class="font-medium">{targetText(request)}</span></div>
					<div><span class="text-muted-foreground">retry</span> <span>{request.retry_count}</span></div>
					{#if request.failure_category}
						<div><span class="text-muted-foreground">실패 유형</span> <span class="text-destructive">{request.failure_category}</span></div>
					{/if}
					{#if request.record_id}
						<div><span class="text-muted-foreground">record_id</span> <span>{request.record_id}</span></div>
					{/if}
					{#if request.applied_request_id}
						<div class="col-span-2">
							<span class="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-800">DB 반영됨 #{request.applied_request_id}</span>
						</div>
					{/if}
				</div>

				<!-- Error -->
				{#if request.error_message}
					<div class="rounded bg-destructive/10 px-3 py-2 text-xs text-destructive">
						{request.error_message}
					</div>
				{/if}

				<!-- Result -->
				{#if request.result}
					<div>
						<div class="mb-1 flex items-center justify-between">
							<span class="text-xs font-medium">분석 결과</span>
							<button class="rounded p-0.5 hover:bg-muted" onclick={() => copy('result', request?.result ?? null)} title="복사">
								<Copy class="h-3 w-3" />
							</button>
						</div>
						{#if parsedResult}
							<pre class="overflow-auto rounded bg-muted/40 p-2 text-xs">{JSON.stringify(parsedResult, null, 2)}</pre>
						{:else}
							<pre class="overflow-auto rounded bg-muted/40 p-2 text-xs">{request.result}</pre>
						{/if}
						{#if copiedField === 'result'}<span class="text-xs text-green-600">복사됨</span>{/if}
					</div>
				{/if}

				<!-- Prompt (collapsible) -->
				<div>
					<button
						class="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
						onclick={() => { showPrompt = !showPrompt; }}
					>
						{#if showPrompt}<ChevronDown class="h-3 w-3" />{:else}<ChevronRight class="h-3 w-3" />{/if}
						프롬프트 {request.prompt ? `(${request.prompt.length}자)` : ''}
					</button>
					{#if showPrompt && request.prompt}
						<div class="mt-1 flex flex-col gap-1">
							<pre class="max-h-40 overflow-auto rounded bg-muted/40 p-2 text-xs">{request.prompt}</pre>
							<button class="self-end text-xs hover:underline" onclick={() => copy('prompt', request?.prompt ?? null)}>
								복사 {copiedField === 'prompt' ? '✓' : ''}
							</button>
						</div>
					{/if}
				</div>

				<!-- Raw response (collapsible) -->
				{#if request.raw_response}
					<div>
						<button
							class="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
							onclick={() => { showRaw = !showRaw; }}
						>
							{#if showRaw}<ChevronDown class="h-3 w-3" />{:else}<ChevronRight class="h-3 w-3" />{/if}
							원본 응답 ({request.raw_response.length}자)
						</button>
						{#if showRaw}
							<div class="mt-1 flex flex-col gap-1">
								<pre class="max-h-40 overflow-auto rounded bg-muted/40 p-2 text-xs">{request.raw_response}</pre>
								<button class="self-end text-xs hover:underline" onclick={() => copy('raw', request?.raw_response ?? null)}>
									복사 {copiedField === 'raw' ? '✓' : ''}
								</button>
							</div>
						{/if}
					</div>
				{/if}

				<!-- cli_options -->
				{#if request.cli_options}
					<div class="rounded bg-muted/40 p-2 text-xs">
						<span class="font-medium">cli_options: </span>{request.cli_options}
					</div>
				{/if}

				<!-- completed record 재분析 deep-link -->
				{#if request.record_id}
					<div class="flex items-center gap-2 rounded bg-muted/30 px-2 py-1.5 text-xs">
						<span class="text-muted-foreground">record #{request.record_id} 재분석이 필요하면</span>
						<a
							href="/plans?id={request.record_id}&tab=archive"
							target="_blank"
							rel="noopener"
							class="text-primary underline hover:no-underline"
						>Archive 탭에서 재분석</a>
					</div>
				{/if}

				<!-- DB stored value comparison -->
				{#if request.related_record}
					<div>
						<button
							class="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
							onclick={() => { showRecord = !showRecord; }}
						>
							{#if showRecord}<ChevronDown class="h-3 w-3" />{:else}<ChevronRight class="h-3 w-3" />{/if}
							DB 저장값 (record #{request.related_record.record_id})
						</button>
						{#if showRecord}
							<div class="mt-1 grid grid-cols-2 gap-1 rounded bg-muted/40 p-2 text-xs">
								{#if request.related_record.category}
									<div><span class="text-muted-foreground">category</span> <span class="font-medium">{request.related_record.category}</span></div>
								{/if}
								{#if request.related_record.trigger}
									<div><span class="text-muted-foreground">trigger</span> <span>{request.related_record.trigger}</span></div>
								{/if}
								{#if request.related_record.tags?.length}
									<div class="col-span-2"><span class="text-muted-foreground">tags</span> {request.related_record.tags.join(', ')}</div>
								{/if}
								{#if request.related_record.summary}
									<div class="col-span-2"><span class="text-muted-foreground">summary</span> <span class="whitespace-pre-wrap">{request.related_record.summary}</span></div>
								{/if}
								{#if request.related_record.intent}
									<div class="col-span-2"><span class="text-muted-foreground">intent</span> {request.related_record.intent}</div>
								{/if}
								{#if request.related_record.analyzed_at}
									<div class="col-span-2 text-muted-foreground">분석 시각: {request.related_record.analyzed_at?.slice(0, 16)}</div>
								{/if}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Audit snapshots (overwritten history) -->
				{#if request.audit_snapshots?.length}
					<div>
						<button
							class="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
							onclick={() => { showAudit = !showAudit; }}
						>
							{#if showAudit}<ChevronDown class="h-3 w-3" />{:else}<ChevronRight class="h-3 w-3" />{/if}
							재분석 이력 ({request.audit_snapshots.length}건)
						</button>
						{#if showAudit}
							<div class="mt-1 space-y-1">
								{#each request.audit_snapshots as snap}
									<div class="rounded bg-muted/30 p-2 text-xs">
										<div class="flex items-center justify-between text-muted-foreground">
											<span>덮어쓰기 #{snap.event_id}</span>
											<span>{snap.created_at?.slice(0, 16)}</span>
										</div>
										{#if snap.prior_category}<div><span class="text-muted-foreground">이전 category</span> {snap.prior_category}</div>{/if}
										{#if snap.prior_tags?.length}<div><span class="text-muted-foreground">이전 tags</span> {snap.prior_tags.join(', ')}</div>{/if}
										{#if snap.prior_summary}<div class="whitespace-pre-wrap text-muted-foreground/80">{snap.prior_summary}</div>{/if}
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
