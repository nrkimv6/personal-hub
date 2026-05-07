<script lang="ts">
	import { RefreshCw, ChevronLeft, ChevronRight } from 'lucide-svelte';
	import { createPagePagination } from '$lib/utils/pagination.svelte';
	import { planRecordsApi } from '$lib/api/plan-records';
	import { archiveScheduleApi } from '$lib/api/plan-records';
	import type { SelectedTarget } from './planArchiveOperationsState.js';
	import { candidateActionLabel } from './planArchiveOperationsState.js';

	interface Props {
		selectedTargets?: SelectedTarget[];
		onQueueSuccess?: (result: { queued: number; imported: number; skipped: number; errors: number }) => void;
	}

	let { selectedTargets = [], onQueueSuccess }: Props = $props();

	const pager = createPagePagination(50);

	let candidates = $state<Array<Record<string, unknown>>>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let selectedKeys = $state<Set<string>>(new Set());
	let previewModal = $state<{ candidate: Record<string, unknown>; content: string } | null>(null);
	let queueing = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await planRecordsApi.listArchiveCandidates({
				skip: (pager.page - 1) * 50,
				limit: 50,
			});
			candidates = ((res as unknown) as { candidates?: Record<string, unknown>[] }).candidates ?? [];
			// ArchiveCandidateSummary에는 total이 없을 수 있음
		} catch (e) {
			error = e instanceof Error ? e.message : '로드 실패';
		} finally {
			loading = false;
		}
	}

	function toggleSelect(key: string) {
		const s = new Set(selectedKeys);
		if (s.has(key)) s.delete(key); else s.add(key);
		selectedKeys = s;
	}

	function toggleAll() {
		if (selectedKeys.size === candidates.length) {
			selectedKeys = new Set();
		} else {
			selectedKeys = new Set(candidates.map((c) => String(c['candidate_key'] ?? c['filename_hash'] ?? '')));
		}
	}

	async function openPreview(candidate: Record<string, unknown>) {
		const key = String(candidate['candidate_key'] ?? candidate['filename_hash'] ?? '');
		if (!key) return;
		try {
			const res = await archiveScheduleApi.previewCandidate(key);
			previewModal = { candidate, content: res.raw_content };
		} catch (e) {
			error = e instanceof Error ? e.message : '미리보기 실패';
		}
	}

	async function queueSelected() {
		if (selectedTargets.length === 0 || selectedKeys.size === 0) return;
		queueing = true;
		try {
			const res = await archiveScheduleApi.queueCandidates({
				candidate_keys: Array.from(selectedKeys),
				selected_targets: selectedTargets,
			});
			onQueueSuccess?.(res);
			selectedKeys = new Set();
			load();
		} catch (e) {
			error = e instanceof Error ? e.message : '큐잉 실패';
		} finally {
			queueing = false;
		}
	}

	$effect(() => { pager.reset(); load(); });
</script>

<div class="space-y-3">
	<div class="flex items-center gap-2">
		<button
			class="rounded border border-border px-2 py-0.5 text-xs hover:bg-muted disabled:opacity-50"
			onclick={queueSelected}
			disabled={selectedKeys.size === 0 || selectedTargets.length === 0 || queueing}
		>
			{queueing ? '큐잉중...' : `선택 큐잉 (${selectedKeys.size}건)`}
		</button>
		{#if selectedTargets.length === 0}
			<span class="text-xs text-yellow-600">target 선택 필요</span>
		{/if}
		<button class="ml-auto rounded p-1 text-muted-foreground hover:bg-muted" onclick={load}>
			<RefreshCw class="h-3 w-3 {loading ? 'animate-spin' : ''}" />
		</button>
	</div>

	{#if error}
		<div class="rounded bg-destructive/10 px-3 py-2 text-xs text-destructive">
			{error} — <button class="underline" onclick={load}>재시도</button>
		</div>
	{:else if loading && candidates.length === 0}
		<div class="space-y-1">
			{#each Array(5) as _}
				<div class="h-8 w-full animate-pulse rounded bg-muted"></div>
			{/each}
		</div>
	{:else if candidates.length === 0}
		<div class="rounded bg-muted/30 py-6 text-center text-xs text-muted-foreground">백로그 없음</div>
	{:else}
		<table class="w-full text-xs">
			<thead>
				<tr class="border-b border-border text-left text-muted-foreground">
					<th class="px-2 py-1.5">
						<input type="checkbox" onchange={toggleAll} checked={selectedKeys.size === candidates.length} />
					</th>
					<th class="px-2 py-1.5">파일</th>
					<th class="px-2 py-1.5">상태</th>
					<th class="px-2 py-1.5">액션</th>
				</tr>
			</thead>
			<tbody>
				{#each candidates as c}
					{@const key = String(c['candidate_key'] ?? c['filename_hash'] ?? '')}
					{@const state = String(c['state'] ?? 'matched')}
					<tr class="border-b border-border/50 hover:bg-muted/30">
						<td class="px-2 py-1">
							<input type="checkbox" checked={selectedKeys.has(key)} onchange={() => toggleSelect(key)} />
						</td>
						<td class="px-2 py-1 max-w-xs truncate">{c['file_path'] ?? c['filename_hash'] ?? '—'}</td>
						<td class="px-2 py-1">
							<span class="rounded px-1.5 py-0.5 text-xs {state === 'file_only' ? 'bg-blue-100 text-blue-700' : state === 'db_only' ? 'bg-yellow-100 text-yellow-700' : 'bg-muted'}">{state}</span>
						</td>
						<td class="px-2 py-1 flex gap-1">
							{#if state === 'file_only'}
								<button
									class="rounded border border-border px-1.5 py-0.5 text-xs hover:bg-muted"
									onclick={() => openPreview(c)}
								>미리보기</button>
							{/if}
							<button
								class="rounded border border-border px-1.5 py-0.5 text-xs hover:bg-muted disabled:opacity-50"
								disabled={selectedTargets.length === 0}
								onclick={async () => {
									if (selectedTargets.length === 0) return;
									try {
										const res = await archiveScheduleApi.queueCandidates({
											candidate_keys: [key],
											selected_targets: selectedTargets,
										});
										onQueueSuccess?.(res);
										load();
									} catch (e) {
										error = e instanceof Error ? e.message : '큐잉 실패';
									}
								}}
							>{candidateActionLabel(state)}</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<div class="flex items-center gap-2 text-xs text-muted-foreground">
			<button disabled={pager.page <= 1} onclick={() => { pager.page -= 1; load(); }} class="rounded p-0.5 hover:bg-muted disabled:opacity-40">
				<ChevronLeft class="h-4 w-4" />
			</button>
			<span>페이지 {pager.page}</span>
			<button onclick={() => { pager.page += 1; load(); }} class="rounded p-0.5 hover:bg-muted">
				<ChevronRight class="h-4 w-4" />
			</button>
		</div>
	{/if}
</div>

<!-- Preview modal -->
{#if previewModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
		<div class="flex max-h-[80vh] w-full max-w-xl flex-col overflow-hidden rounded-lg bg-background shadow-xl">
			<div class="flex items-center justify-between border-b border-border px-4 py-3">
				<h3 class="text-sm font-semibold">파일 미리보기</h3>
				<button onclick={() => { previewModal = null; }} class="rounded p-1 hover:bg-muted">닫기</button>
			</div>
			<pre class="flex-1 overflow-auto p-4 text-xs">{previewModal.content}</pre>
			<div class="flex justify-end gap-2 border-t border-border px-4 py-3">
				<button
					class="rounded border border-border px-3 py-1 text-xs hover:bg-muted"
					onclick={() => { previewModal = null; }}
				>취소</button>
				<button
					class="rounded bg-primary px-3 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
					disabled={selectedTargets.length === 0}
					onclick={async () => {
						const key = String(previewModal?.candidate['candidate_key'] ?? previewModal?.candidate['filename_hash'] ?? '');
						try {
							const res = await archiveScheduleApi.queueCandidates({
								candidate_keys: [key],
								selected_targets: selectedTargets,
							});
							onQueueSuccess?.(res);
							previewModal = null;
							load();
						} catch (e) {
							error = e instanceof Error ? e.message : '큐잉 실패';
						}
					}}
				>임포트 + 큐잉</button>
			</div>
		</div>
	</div>
{/if}
