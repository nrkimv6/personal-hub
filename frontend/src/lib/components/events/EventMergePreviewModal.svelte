<script lang="ts">
	import { Button, Modal } from '$lib/components/ui';
	import { eventDuplicateApi } from '$lib/api';
	import type {
		DuplicateCandidate,
		MergeExecuteResponse,
		MergeFieldComparison,
		MergeFieldSource,
		MergePreview
	} from '$lib/types';
	import { toast } from '$lib/stores/toast';
	import { GitMerge } from 'lucide-svelte';

	interface Props {
		open: boolean;
		candidate: DuplicateCandidate | null;
		onClose: () => void;
		onMerged: (result: MergeExecuteResponse) => void;
	}

	let { open, candidate, onClose, onMerged }: Props = $props();

	let preview: MergePreview | null = $state(null);
	let loading = $state(false);
	let merging = $state(false);
	let error: string | null = $state(null);
	let selectedPrimaryId: number | null = $state(null);
	let fieldSelections: Record<string, MergeFieldSource> = $state({});
	let lastPreviewKey = $state('');

	const primaryId = $derived(selectedPrimaryId ?? candidate?.primary.id ?? null);
	const secondaryId = $derived.by(() => {
		if (!candidate || !primaryId) return null;
		return primaryId === candidate.primary.id ? candidate.secondary.id : candidate.primary.id;
	});

	function valueText(value: unknown): string {
		if (value === null || value === undefined || value === '') return '-';
		if (Array.isArray(value)) return value.length ? value.join(', ') : '-';
		if (typeof value === 'boolean') return value ? '예' : '아니오';
		return String(value);
	}

	function resetSelections(fields: MergeFieldComparison[]) {
		fieldSelections = Object.fromEntries(fields.map((field) => [field.field, field.selected_source]));
	}

	async function loadPreview() {
		if (!candidate || !primaryId || !secondaryId) return;
		loading = true;
		error = null;
		try {
			preview = await eventDuplicateApi.preview(primaryId, secondaryId);
			resetSelections(preview.fields);
		} catch (e) {
			error = e instanceof Error ? e.message : '미리보기 로드 실패';
		} finally {
			loading = false;
		}
	}

	function setPrimary(id: number) {
		if (selectedPrimaryId === id) return;
		selectedPrimaryId = id;
		lastPreviewKey = '';
	}

	function setField(field: string, source: MergeFieldSource) {
		fieldSelections = { ...fieldSelections, [field]: source };
	}

	async function executeMerge() {
		if (!preview) return;
		merging = true;
		try {
			const result = await eventDuplicateApi.merge({
				primary_id: preview.primary_id,
				secondary_id: preview.secondary_id,
				field_selections: fieldSelections
			});
			toast.success('이벤트를 병합했습니다.');
			onMerged(result);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '병합 실패');
		} finally {
			merging = false;
		}
	}

	$effect(() => {
		if (!open || !candidate) {
			preview = null;
			error = null;
			lastPreviewKey = '';
			return;
		}
		if (!selectedPrimaryId || ![candidate.primary.id, candidate.secondary.id].includes(selectedPrimaryId)) {
			selectedPrimaryId = candidate.primary.id;
		}
		const key = `${candidate.entity1_id}:${candidate.entity2_id}:${primaryId}:${secondaryId}`;
		if (primaryId && secondaryId && key !== lastPreviewKey) {
			lastPreviewKey = key;
			loadPreview();
		}
	});
</script>

{#snippet footer()}
	<Button variant="outline" size="sm" onclick={onClose} disabled={merging}>닫기</Button>
	<Button variant="primary" size="sm" onclick={executeMerge} disabled={!preview || merging} loading={merging} title="선택한 필드로 병합">
		<GitMerge size={16} />
		병합 실행
	</Button>
{/snippet}

<Modal open={open} title="중복 이벤트 병합" size="xl" {onClose} footer={footer}>
	{#if !candidate}
		<div class="py-8 text-center text-sm text-muted-foreground">선택된 후보가 없습니다.</div>
	{:else}
		<div class="space-y-4">
			<div class="grid gap-3 md:grid-cols-2">
				{#each [candidate.primary, candidate.secondary] as event}
					<button
						type="button"
						class="rounded-lg border p-3 text-left transition-colors {primaryId === event.id ? 'border-primary bg-primary/5' : 'border-border bg-card hover:bg-muted'}"
						onclick={() => setPrimary(event.id)}
					>
						<div class="mb-1 flex items-center justify-between gap-2">
							<span class="text-xs font-medium text-muted-foreground">ID {event.id}</span>
							<span class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
								{primaryId === event.id ? 'primary' : 'secondary'}
							</span>
						</div>
						<div class="font-medium text-foreground">{event.title}</div>
						<div class="mt-1 text-xs text-muted-foreground">{event.organizer || '-'} · 출처 {event.source_count}개</div>
					</button>
				{/each}
			</div>

			{#if loading}
				<div class="py-8 text-center text-sm text-muted-foreground">미리보기를 불러오는 중입니다.</div>
			{:else if error}
				<div class="rounded-lg border border-error/30 bg-error-light px-3 py-2 text-sm text-error">{error}</div>
			{:else if preview}
				<div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
					<span>유사도 {Math.round(preview.similarity * 100)}%</span>
					<span>primary 출처 {preview.primary_source_count}개</span>
					<span>secondary 출처 {preview.secondary_source_count}개는 병합 후 primary로 이동</span>
				</div>

				<div class="overflow-x-auto rounded-lg border border-border">
					<table class="w-full text-sm">
						<thead class="bg-muted text-xs text-muted-foreground">
							<tr>
								<th class="px-3 py-2 text-left font-medium">필드</th>
								<th class="px-3 py-2 text-left font-medium">Primary</th>
								<th class="px-3 py-2 text-left font-medium">Secondary</th>
								<th class="px-3 py-2 text-left font-medium">선택</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each preview.fields as field}
								<tr>
									<td class="px-3 py-2 font-medium text-foreground">{field.label}</td>
									<td class="max-w-[18rem] px-3 py-2 text-muted-foreground">{valueText(field.primary_value)}</td>
									<td class="max-w-[18rem] px-3 py-2 text-muted-foreground">{valueText(field.secondary_value)}</td>
									<td class="px-3 py-2">
										<select
											class="rounded-md border border-input bg-background px-2 py-1 text-sm"
											value={fieldSelections[field.field] || 'primary'}
											onchange={(e) => setField(field.field, (e.currentTarget as HTMLSelectElement).value as MergeFieldSource)}
										>
											<option value="primary">primary 유지</option>
											<option value="secondary">secondary 사용</option>
										</select>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<div class="rounded-lg border border-warning/30 bg-warning-light px-3 py-2 text-sm text-warning">
					병합 실행 후 secondary 이벤트는 삭제되지 않고 disabled 상태로 전환됩니다.
				</div>
			{/if}
		</div>
	{/if}
</Modal>
