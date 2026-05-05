<script lang="ts">
	import { onMount } from 'svelte';
	import {
		planRecordsApi,
		type PlanArchiveDocPatchProposal,
		type PlanArchiveInsightCandidate,
		type PlanArchiveInsightReport,
		type PlanArchiveInsightReportDetail
	} from '$lib/api/plan-records';

	let reports: PlanArchiveInsightReport[] = $state([]);
	let selected: PlanArchiveInsightReportDetail | null = $state(null);
	let evidencePreview: Record<string, unknown> | null = $state(null);
	let loading = $state(false);
	let detailLoading = $state(false);
	let error = $state('');
	let statusFilter = $state('');
	let reviewFilter = $state('');
	let groupingFilter = $state('');
	let reviewNote = $state('');
	let promoteConfirmIndex: number | null = $state(null);
	let patchPreview: PlanArchiveDocPatchProposal | null = $state(null);
	let patchError = $state('');
	let patchRecordId = $state('');
	let patchOldText = $state('');
	let patchNewText = $state('');
	let patchConfirm = $state(false);
	const pageSize = 50;

	const reviewStatuses = [
		{ value: '', label: '전체 검토' },
		{ value: 'unreviewed', label: '미검토' },
		{ value: 'reviewing', label: '검토중' },
		{ value: 'accepted', label: '채택' },
		{ value: 'rejected', label: '반려' },
		{ value: 'promoted', label: '승격' }
	];

	function formatDate(value: string | null | undefined) {
		if (!value) return '-';
		return new Date(value).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
	}

	function reviewLabel(value: string) {
		return reviewStatuses.find((item) => item.value === value)?.label ?? value;
	}

	function evidenceKey(item: Record<string, unknown>, index: number) {
		return `${item.record_id ?? 'r'}-${item.chunk_id ?? item.file_ref_id ?? index}`;
	}

	async function loadReports() {
		loading = true;
		error = '';
		try {
			const result = await planRecordsApi.listInsightReports({
				status: statusFilter || undefined,
				review_status: reviewFilter || undefined,
				grouping: groupingFilter || undefined,
				limit: pageSize
			});
			reports = result.items ?? [];
			if (selected && !reports.some((report) => report.id === selected?.id)) {
				selected = null;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'insight report 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function selectReport(report: PlanArchiveInsightReport) {
		detailLoading = true;
		error = '';
		evidencePreview = null;
		try {
			selected = await planRecordsApi.getInsightReport(report.id);
			reviewNote = selected.review_note ?? '';
		} catch (e) {
			error = e instanceof Error ? e.message : 'report 상세 로드 실패';
		} finally {
			detailLoading = false;
		}
	}

	async function updateReview(status: 'reviewing' | 'accepted' | 'rejected') {
		if (!selected) return;
		try {
			selected = await planRecordsApi.updateInsightReport(selected.id, {
				review_status: status,
				review_note: reviewNote || null
			});
			reports = reports.map((report) => report.id === selected?.id ? { ...report, ...selected } : report);
		} catch (e) {
			error = e instanceof Error ? e.message : '검토 상태 저장 실패';
		}
	}

	async function openEvidence(item: Record<string, unknown>) {
		if (!selected) return;
		const chunkId = Number(item.chunk_id ?? 0);
		const fileRefId = Number(item.file_ref_id ?? 0);
		const recordId = Number(item.record_id ?? 0);
		const sourceType = chunkId ? 'chunk' : fileRefId ? 'file_ref' : 'record';
		const sourceId = chunkId || fileRefId || recordId;
		if (!sourceId) {
			evidencePreview = { warning: 'source 없음', item };
			return;
		}
		try {
			evidencePreview = await planRecordsApi.getInsightEvidence(selected.id, sourceType, sourceId);
		} catch (e) {
			evidencePreview = { error: e instanceof Error ? e.message : 'evidence 조회 실패', item };
		}
	}

	function openDocPatch(recommendation: string) {
		const source = selected?.evidence.find((item) => Number(item.record_id ?? 0));
		patchRecordId = source ? String(source.record_id) : '';
		patchOldText = recommendation;
		patchNewText = recommendation;
		patchPreview = null;
		patchError = '';
		patchConfirm = false;
	}

	async function previewDocPatch() {
		if (!selected || !patchRecordId) {
			patchError = 'record id가 필요합니다.';
			return;
		}
		try {
			patchPreview = await planRecordsApi.previewDocPatch({
				record_id: Number(patchRecordId),
				insight_report_id: selected.id,
				patch_text: JSON.stringify({ replacements: [{ old: patchOldText, new: patchNewText }] })
			});
			patchError = '';
			patchConfirm = false;
		} catch (e) {
			patchError = e instanceof Error ? e.message : 'patch preview 실패';
		}
	}

	async function applyDocPatch() {
		if (!patchPreview) return;
		if (!patchConfirm) {
			patchConfirm = true;
			return;
		}
		try {
			patchPreview = await planRecordsApi.applyDocPatch(patchPreview.id, { confirm: true });
			patchError = '';
			patchConfirm = false;
		} catch (e) {
			patchError = e instanceof Error ? e.message : 'patch apply 실패';
		}
	}

	async function promoteCandidate(index: number, candidate: PlanArchiveInsightCandidate) {
		if (!selected) return;
		if (promoteConfirmIndex !== index) {
			promoteConfirmIndex = index;
			return;
		}
		try {
			const result = await planRecordsApi.promoteInsightPlan(selected.id, {
				candidate_index: index,
				confirm: true,
				title: candidate.title ?? null
			});
			selected = result.report;
			reports = reports.map((report) => report.id === selected?.id ? { ...report, ...selected } : report);
			promoteConfirmIndex = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '계획 후보 승격 실패';
		}
	}

	onMount(() => {
		void loadReports();
	});
</script>

<div class="flex h-full min-h-0 flex-col gap-3">
	<div class="flex flex-wrap items-center gap-2">
		<h2 class="text-sm font-semibold text-foreground">Insight reports</h2>
		<select class="rounded border border-border bg-background px-2 py-1 text-xs" bind:value={statusFilter} onchange={() => loadReports()}>
			<option value="">전체 상태</option>
			<option value="completed">completed</option>
			<option value="pending">pending</option>
			<option value="failed">failed</option>
		</select>
		<select class="rounded border border-border bg-background px-2 py-1 text-xs" bind:value={reviewFilter} onchange={() => loadReports()}>
			{#each reviewStatuses as status}
				<option value={status.value}>{status.label}</option>
			{/each}
		</select>
		<input
			class="w-32 rounded border border-border bg-background px-2 py-1 text-xs"
			placeholder="grouping"
			bind:value={groupingFilter}
			onkeydown={(event) => { if (event.key === 'Enter') void loadReports(); }}
		/>
		<button class="rounded bg-muted px-3 py-1 text-xs hover:bg-secondary" onclick={() => loadReports()} disabled={loading}>
			{loading ? '갱신 중' : '갱신'}
		</button>
	</div>

	{#if error}
		<div class="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
	{/if}

	<div class="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(260px,360px)_1fr]">
		<div class="min-h-0 overflow-auto rounded-lg border border-border bg-card">
			{#if loading && reports.length === 0}
				<div class="p-4 text-sm text-muted-foreground">로드 중...</div>
			{:else if reports.length === 0}
				<div class="p-4 text-sm text-muted-foreground">report가 없습니다.</div>
			{:else}
				{#each reports as report (report.id)}
					<button
						class="w-full border-b border-border/60 px-3 py-3 text-left hover:bg-muted/40 {selected?.id === report.id ? 'bg-muted/60' : ''}"
						onclick={() => selectReport(report)}
					>
						<div class="flex items-center justify-between gap-2">
							<span class="truncate text-sm font-medium text-foreground">#{report.id} {report.summary ?? report.grouping}</span>
							<span class="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{reviewLabel(report.review_status)}</span>
						</div>
						<div class="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
							<span>{report.grouping}</span>
							<span>{report.provider}/{report.model || '-'}</span>
							<span>{formatDate(report.completed_at ?? report.created_at)}</span>
						</div>
					</button>
				{/each}
			{/if}
		</div>

		<div class="min-h-0 overflow-auto rounded-lg border border-border bg-card p-4">
			{#if detailLoading}
				<p class="text-sm text-muted-foreground">상세 로드 중...</p>
			{:else if !selected}
				<p class="text-sm text-muted-foreground">report를 선택하세요.</p>
			{:else}
				<div class="space-y-4">
					<div class="flex flex-wrap items-start justify-between gap-3">
						<div>
							<h3 class="text-base font-semibold text-foreground">Report #{selected.id}</h3>
							<p class="mt-1 text-sm text-muted-foreground">{selected.summary ?? 'summary 없음'}</p>
						</div>
						<div class="flex flex-wrap gap-2">
							<button class="rounded bg-muted px-3 py-1 text-xs hover:bg-secondary" onclick={() => updateReview('reviewing')}>검토중</button>
							<button class="rounded bg-green-100 px-3 py-1 text-xs text-green-700 hover:bg-green-200" onclick={() => updateReview('accepted')}>채택</button>
							<button class="rounded bg-red-100 px-3 py-1 text-xs text-red-700 hover:bg-red-200" onclick={() => updateReview('rejected')}>반려</button>
						</div>
					</div>

					<textarea
						class="h-20 w-full rounded border border-border bg-background px-3 py-2 text-sm"
						placeholder="review note"
						bind:value={reviewNote}
					></textarea>

					<section>
						<h4 class="mb-2 text-sm font-semibold text-foreground">Root causes</h4>
						<div class="space-y-2">
							{#each selected.root_causes as item}
								<div class="rounded border border-border bg-background px-3 py-2 text-sm">{item}</div>
							{/each}
						</div>
					</section>

					<section>
						<h4 class="mb-2 text-sm font-semibold text-foreground">Recommendations</h4>
						<div class="space-y-2">
							{#each selected.recommendations as item}
								<div class="rounded border border-border bg-background px-3 py-2 text-sm">
									<div>{item}</div>
									<button class="mt-2 rounded bg-muted px-2 py-1 text-xs hover:bg-secondary" onclick={() => openDocPatch(item)}>
										patch proposal
									</button>
								</div>
							{/each}
						</div>
					</section>

					<section class="rounded border border-border bg-background p-3">
						<h4 class="mb-2 text-sm font-semibold text-foreground">Doc patch proposal</h4>
						<div class="grid gap-2 md:grid-cols-[120px_1fr_1fr_auto]">
							<input class="rounded border border-border bg-background px-2 py-1 text-xs" placeholder="record id" bind:value={patchRecordId} />
							<input class="rounded border border-border bg-background px-2 py-1 text-xs" placeholder="old text" bind:value={patchOldText} />
							<input class="rounded border border-border bg-background px-2 py-1 text-xs" placeholder="new text" bind:value={patchNewText} />
							<button class="rounded bg-muted px-3 py-1 text-xs hover:bg-secondary" onclick={previewDocPatch}>Preview</button>
						</div>
						{#if patchError}
							<div class="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700">{patchError}</div>
						{/if}
						{#if patchPreview}
							<div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
								<span>{patchPreview.status} · {patchPreview.target_path}</span>
								<button class="rounded bg-primary px-3 py-1 text-primary-foreground hover:bg-primary/90" onclick={applyDocPatch}>
									{patchConfirm ? 'Confirm apply' : 'Apply'}
								</button>
							</div>
							<pre class="mt-2 max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{patchPreview.preview_text}</pre>
						{/if}
					</section>

					<section>
						<h4 class="mb-2 text-sm font-semibold text-foreground">Candidates</h4>
						<div class="space-y-2">
							{#each selected.suggested_plan_candidates as candidate, index}
								<div class="rounded border border-border bg-background px-3 py-2">
									<div class="flex flex-wrap items-center justify-between gap-2">
										<div class="min-w-0">
											<div class="truncate text-sm font-medium">{candidate.title ?? `Candidate ${index + 1}`}</div>
											<div class="text-xs text-muted-foreground">{candidate.reason ?? 'reason 없음'}</div>
										</div>
										<button class="rounded bg-primary px-3 py-1 text-xs text-primary-foreground hover:bg-primary/90" onclick={() => promoteCandidate(index, candidate)}>
											{promoteConfirmIndex === index ? '확인' : '승격'}
										</button>
									</div>
									{#if !candidate.evidence_ids || candidate.evidence_ids.length === 0}
										<div class="mt-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-700">source 없음</div>
									{/if}
								</div>
							{/each}
						</div>
					</section>

					<section>
						<h4 class="mb-2 text-sm font-semibold text-foreground">Evidence</h4>
						<div class="grid gap-2 md:grid-cols-2">
							{#each selected.evidence as item, index (evidenceKey(item, index))}
								<button class="rounded border border-border bg-background px-3 py-2 text-left text-xs hover:bg-muted/40" onclick={() => openEvidence(item)}>
									<div class="font-medium">record {String(item.record_id ?? '-')}</div>
									<div class="truncate text-muted-foreground">{String(item.heading ?? item.path ?? item.text ?? 'source 없음')}</div>
								</button>
							{/each}
						</div>
						{#if evidencePreview}
							<pre class="mt-3 max-h-72 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(evidencePreview, null, 2)}</pre>
						{/if}
					</section>

					<details class="rounded border border-border bg-background p-3">
						<summary class="cursor-pointer text-sm font-medium">Raw JSON</summary>
						<pre class="mt-3 max-h-80 overflow-auto text-xs">{JSON.stringify(selected.insight, null, 2)}</pre>
					</details>
				</div>
			{/if}
		</div>
	</div>
</div>
