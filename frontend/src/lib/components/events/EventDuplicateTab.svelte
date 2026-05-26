<script lang="ts">
	import { Button } from '$lib/components/ui';
	import { eventDuplicateApi } from '$lib/api';
	import type { DuplicateCandidate, MergeExecuteResponse } from '$lib/types';
	import { toast } from '$lib/stores/toast';
	import { Eye, GitMerge, RefreshCw, XCircle } from 'lucide-svelte';
	import EventMergePreviewModal from './EventMergePreviewModal.svelte';

	let candidates: DuplicateCandidate[] = $state([]);
	let loading = $state(false);
	let error: string | null = $state(null);
	let minSimilarity = $state(0.5);
	let maxSimilarity = $state(0.99);
	let limit = $state(50);
	let dismissingPair: string | null = $state(null);
	let selectedCandidate: DuplicateCandidate | null = $state(null);
	let showPreview = $state(false);

	function percent(value: number): string {
		return `${Math.round(value * 100)}%`;
	}

	function pairKey(candidate: DuplicateCandidate): string {
		return `${candidate.entity1_id}:${candidate.entity2_id}`;
	}

	function formatDate(value: string | null): string {
		if (!value) return '-';
		return value.slice(0, 10);
	}

	async function loadCandidates() {
		loading = true;
		error = null;
		try {
			candidates = await eventDuplicateApi.candidates({
				min_similarity: minSimilarity,
				max_similarity: maxSimilarity,
				limit
			});
		} catch (e) {
			error = e instanceof Error ? e.message : '중복 후보를 불러오지 못했습니다.';
		} finally {
			loading = false;
		}
	}

	function openPreview(candidate: DuplicateCandidate) {
		selectedCandidate = candidate;
		showPreview = true;
	}

	async function dismissCandidate(candidate: DuplicateCandidate) {
		const key = pairKey(candidate);
		dismissingPair = key;
		try {
			await eventDuplicateApi.dismiss(candidate.entity1_id, candidate.entity2_id);
			candidates = candidates.filter((item) => pairKey(item) !== key);
			toast.success('중복 아님으로 처리했습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '중복 아님 처리 실패');
		} finally {
			dismissingPair = null;
		}
	}

	function handleMerged(result: MergeExecuteResponse) {
		candidates = candidates.filter(
			(item) => ![item.entity1_id, item.entity2_id].includes(result.disabled_id)
		);
		showPreview = false;
		selectedCandidate = null;
	}

	$effect(() => {
		loadCandidates();
	});
</script>

<div class="space-y-3">
	<div class="flex flex-col gap-3 rounded-lg border border-border bg-card p-3 md:flex-row md:items-end md:justify-between">
		<div class="grid grid-cols-3 gap-2 md:w-[28rem]">
			<label class="text-xs font-medium text-muted-foreground">
				최소 유사도
				<input
					type="number"
					min="0"
					max="1"
					step="0.05"
					bind:value={minSimilarity}
					class="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm text-foreground"
				/>
			</label>
			<label class="text-xs font-medium text-muted-foreground">
				최대 유사도
				<input
					type="number"
					min="0"
					max="1"
					step="0.05"
					bind:value={maxSimilarity}
					class="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm text-foreground"
				/>
			</label>
			<label class="text-xs font-medium text-muted-foreground">
				제한
				<input
					type="number"
					min="1"
					max="200"
					step="1"
					bind:value={limit}
					class="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm text-foreground"
				/>
			</label>
		</div>
		<Button variant="outline" size="sm" onclick={loadCandidates} disabled={loading} loading={loading} title="후보 새로고침">
			<RefreshCw size={16} />
			새로고침
		</Button>
	</div>

	{#if error}
		<div class="rounded-lg border border-error/30 bg-error-light px-3 py-2 text-sm text-error">{error}</div>
	{:else if loading}
		<div class="py-12 text-center text-sm text-muted-foreground">중복 후보를 불러오는 중입니다.</div>
	{:else if candidates.length === 0}
		<div class="py-12 text-center text-sm text-muted-foreground">검토할 중복 후보가 없습니다.</div>
	{:else}
		<div class="overflow-x-auto rounded-lg border border-border bg-card">
			<table class="w-full text-sm">
				<thead class="border-b border-border bg-muted text-xs text-muted-foreground">
					<tr>
						<th class="px-3 py-2 text-left font-medium">유사도</th>
						<th class="px-3 py-2 text-left font-medium">Primary</th>
						<th class="px-3 py-2 text-left font-medium">Secondary</th>
						<th class="px-3 py-2 text-left font-medium">근거</th>
						<th class="px-3 py-2 text-right font-medium">작업</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-border">
					{#each candidates as candidate (pairKey(candidate))}
						<tr>
							<td class="px-3 py-3 align-top">
								<span class="rounded-full bg-primary/10 px-2 py-1 text-xs font-semibold text-primary">
									{percent(candidate.similarity)}
								</span>
							</td>
							<td class="max-w-[20rem] px-3 py-3 align-top">
								<div class="font-medium text-foreground">{candidate.primary.title}</div>
								<div class="mt-1 text-xs text-muted-foreground">
									ID {candidate.primary.id} · {candidate.primary.organizer || '-'} · {formatDate(candidate.primary.event_end)}
								</div>
							</td>
							<td class="max-w-[20rem] px-3 py-3 align-top">
								<div class="font-medium text-foreground">{candidate.secondary.title}</div>
								<div class="mt-1 text-xs text-muted-foreground">
									ID {candidate.secondary.id} · {candidate.secondary.organizer || '-'} · {formatDate(candidate.secondary.event_end)}
								</div>
							</td>
							<td class="px-3 py-3 align-top">
								<div class="flex max-w-[16rem] flex-wrap gap-1">
									{#each candidate.matched_fields as field}
										<span class="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{field}</span>
									{/each}
								</div>
							</td>
							<td class="px-3 py-3 align-top">
								<div class="flex justify-end gap-1">
									<Button variant="ghost" size="icon" onclick={() => openPreview(candidate)} title="병합 미리보기">
										<Eye size={16} />
									</Button>
									<Button variant="primary" size="icon" onclick={() => openPreview(candidate)} title="병합">
										<GitMerge size={16} />
									</Button>
									<Button
										variant="outline"
										size="icon"
										onclick={() => dismissCandidate(candidate)}
										disabled={dismissingPair === pairKey(candidate)}
										title="중복 아님"
									>
										<XCircle size={16} />
									</Button>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<EventMergePreviewModal
	open={showPreview}
	candidate={selectedCandidate}
	onClose={() => {
		showPreview = false;
		selectedCandidate = null;
	}}
	onMerged={handleMerged}
/>
