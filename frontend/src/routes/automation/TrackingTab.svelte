<script lang="ts">
	import { onMount } from 'svelte';
	import { ChevronDown, Copy, ExternalLink, FolderOpen } from 'lucide-svelte';
	import { trackingApi, type TrackingItem, type TrackingStatus } from '$lib/api/tracking';
	import { toast } from '$lib/stores/toast';
	import {
		copyPlanPath,
		getPlanActionDisabledReason,
		getPlanDisplayName,
		openPlanInEditor,
		openPlanInExplorer
	} from '$lib/utils/plan-actions';
	import {
		TRACKING_FILTERS,
		buildTrackingPayload,
		getTrackingStatusClass,
		getTrackingStatusLabel,
		sortTrackingItems
	} from '$lib/utils/tracking.js';
	import TrackingPlanPicker from './TrackingPlanPicker.svelte';
	import type { LinkedPlan } from '$lib/api/tracking';

	type Filter = TrackingStatus | 'all';

	let items: TrackingItem[] = $state([]);
	let loading = $state(true);
	let saving = $state(false);
	let error = $state('');
	let activeFilter = $state<Filter>('all');
	let showModal = $state(false);
	let editingItem = $state<TrackingItem | null>(null);
	let form = $state({ title: '', description: '', start_at: '', due_at: '' });
	let pickerValue = $state<number[]>([]);
	let pickerSaving = $state(false);
	let expandedPlansItemId = $state<number | null>(null);

	const summary = $derived({
		total: items.length,
		overdue: items.filter((item) => item.status === 'overdue').length,
		ready: items.filter((item) => item.status === 'ready').length,
		upcoming: items.filter((item) => item.status === 'upcoming').length,
		done: items.filter((item) => item.status === 'done').length
	});

	onMount(async () => {
		await loadItems();
	});

	async function loadItems() {
		loading = true;
		error = '';
		try {
			const response = await trackingApi.list({ status: activeFilter, include_done: true });
			items = response.items;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Tracking 항목을 불러오지 못했습니다.';
		} finally {
			loading = false;
		}
	}

	function toInputValue(value?: string | null) {
		return value ? value.slice(0, 16) : '';
	}

	function formatDate(value?: string | null) {
		if (!value) return '-';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString('ko-KR', {
			month: '2-digit',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function openCreateModal() {
		editingItem = null;
		form = { title: '', description: '', start_at: '', due_at: '' };
		pickerValue = [];
		showModal = true;
	}

	function openEditModal(item: TrackingItem) {
		editingItem = item;
		form = {
			title: item.title,
			description: item.description ?? '',
			start_at: toInputValue(item.start_at),
			due_at: toInputValue(item.due_at)
		};
		pickerValue = [];
		showModal = true;
	}

	function togglePlanActions(itemId: number) {
		expandedPlansItemId = expandedPlansItemId === itemId ? null : itemId;
	}

	function stopPlanAction(event: MouseEvent) {
		event.stopPropagation();
	}

	async function handleCopyPlanPath(plan: LinkedPlan) {
		const disabledReason = getPlanActionDisabledReason(plan);
		if (disabledReason) {
			toast.warning(disabledReason);
			return;
		}
		try {
			await copyPlanPath(plan.file_path);
			toast.success('계획서 경로를 복사했습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '계획서 경로 복사 실패');
		}
	}

	async function handleOpenPlanInEditor(plan: LinkedPlan) {
		const disabledReason = getPlanActionDisabledReason(plan);
		if (disabledReason) {
			toast.warning(disabledReason);
			return;
		}
		try {
			await openPlanInEditor(plan.file_path);
			toast.success('VSCode에서 계획서를 여는 요청을 보냈습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '계획서 열기 실패');
		}
	}

	async function handleOpenPlanInExplorer(plan: LinkedPlan) {
		const disabledReason = getPlanActionDisabledReason(plan);
		if (disabledReason) {
			toast.warning(disabledReason);
			return;
		}
		try {
			await openPlanInExplorer(plan.file_path);
			toast.success('계획서 폴더 경로를 복사했습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '계획서 폴더 경로 복사 실패');
		}
	}

	async function saveItem() {
		if (saving) return;
		let payload;
		try {
			payload = buildTrackingPayload(form);
		} catch (e) {
			toast.warning(e instanceof Error ? e.message : '입력값을 확인하세요.');
			return;
		}

		saving = true;
		try {
			if (editingItem) {
				const updated = await trackingApi.update(editingItem.id, payload);
				const nextItems = items.map((item) => (item.id === updated.id ? updated : item));
				items = activeFilter === 'all' || updated.status === activeFilter
					? sortTrackingItems(nextItems)
					: nextItems.filter((item) => item.id !== updated.id);
				toast.success('Tracking 항목을 수정했습니다.');
				// plan 링크 diff 처리
				if (pickerValue.length > 0) {
					try {
						const linked = await trackingApi.linkPlans(updated.id, pickerValue);
						const nextItems2 = items.map((item) => (item.id === linked.id ? linked : item));
						items = activeFilter === 'all' || linked.status === activeFilter
							? sortTrackingItems(nextItems2)
							: nextItems2.filter((item) => item.id !== linked.id);
					} catch {
						toast.error('항목은 수정됐지만 plan 연결에 실패했습니다.');
					}
				}
			} else {
				const created = await trackingApi.create(payload);
				items = activeFilter === 'all' || created.status === activeFilter
					? sortTrackingItems([created, ...items])
					: items;
				toast.success('Tracking 항목을 추가했습니다.');
				// 신규 항목 생성 후 plan 링크
				if (pickerValue.length > 0) {
					try {
						const linked = await trackingApi.linkPlans(created.id, pickerValue);
						items = activeFilter === 'all' || linked.status === activeFilter
							? sortTrackingItems([linked, ...items.filter((i) => i.id !== linked.id)])
							: items;
					} catch {
						toast.error('항목은 추가됐지만 plan 연결에 실패했습니다.');
					}
				}
			}
			showModal = false;
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '저장 실패');
		} finally {
			saving = false;
		}
	}

	async function toggleComplete(item: TrackingItem) {
		try {
			const updated =
				item.status === 'done'
					? await trackingApi.reopen(item.id)
					: await trackingApi.complete(item.id);
			const nextItems = items.map((candidate) => (candidate.id === updated.id ? updated : candidate));
			items = activeFilter === 'all' || updated.status === activeFilter
				? sortTrackingItems(nextItems)
				: nextItems.filter((candidate) => candidate.id !== updated.id);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '완료 상태 변경 실패');
		}
	}

	async function deleteItem(item: TrackingItem) {
		try {
			await trackingApi.delete(item.id);
			items = items.filter((candidate) => candidate.id !== item.id);
			toast.success('Tracking 항목을 삭제했습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '삭제 실패');
		}
	}

	async function changeFilter(filter: string) {
		activeFilter = filter as Filter;
		await loadItems();
	}
</script>

<div class="h-full overflow-auto p-4 lg:p-6">
	<div class="mx-auto max-w-7xl space-y-5">
		<section class="rounded-2xl border border-border bg-card p-5 shadow-sm">
			<div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
				<div>
					<p class="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">Deadline Tracking</p>
					<h2 class="mt-2 text-2xl font-bold text-foreground">Tracking</h2>
					<p class="mt-2 max-w-2xl text-sm text-muted-foreground">
						plan과 독립적으로 관리하는 시작가능일/마감기한 기반 추적 리스트입니다.
					</p>
				</div>
				<button
					class="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
					onclick={openCreateModal}
				>
					항목 추가
				</button>
			</div>

			<div class="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5">
				<div class="rounded-xl bg-muted/40 p-3"><div class="text-xs text-muted-foreground">전체</div><div class="mt-1 text-xl font-bold">{summary.total}</div></div>
				<div class="rounded-xl bg-red-50 p-3 text-red-700 dark:bg-red-950/30 dark:text-red-300"><div class="text-xs">지연</div><div class="mt-1 text-xl font-bold">{summary.overdue}</div></div>
				<div class="rounded-xl bg-emerald-50 p-3 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"><div class="text-xs">준비됨</div><div class="mt-1 text-xl font-bold">{summary.ready}</div></div>
				<div class="rounded-xl bg-blue-50 p-3 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300"><div class="text-xs">예정</div><div class="mt-1 text-xl font-bold">{summary.upcoming}</div></div>
				<div class="rounded-xl bg-slate-50 p-3 text-slate-700 dark:bg-slate-900 dark:text-slate-300"><div class="text-xs">완료</div><div class="mt-1 text-xl font-bold">{summary.done}</div></div>
			</div>
		</section>

		<section class="rounded-2xl border border-border bg-card shadow-sm">
			<div class="flex flex-wrap items-center gap-2 border-b border-border p-4">
				{#each TRACKING_FILTERS as filter}
					<button
						class="rounded-full px-3 py-1.5 text-sm transition-colors {activeFilter === filter ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-muted/80'}"
						onclick={() => changeFilter(filter)}
					>
						{filter === 'all' ? '전체' : getTrackingStatusLabel(filter)}
					</button>
				{/each}
			</div>

			{#if error}
				<div class="m-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
			{/if}

			{#if loading}
				<div class="p-10 text-center text-sm text-muted-foreground">Tracking 항목을 불러오는 중...</div>
			{:else if items.length === 0}
				<div class="p-10 text-center">
					<div class="text-lg font-semibold">표시할 항목이 없습니다.</div>
					<p class="mt-2 text-sm text-muted-foreground">시작가능일 또는 마감기한이 있는 항목을 추가하세요.</p>
				</div>
			{:else}
				<div class="divide-y divide-border">
					{#each items as item (item.id)}
						<article class="p-4 transition-colors hover:bg-muted/20">
							<div class="flex flex-col gap-4 lg:flex-row lg:items-center">
								<div class="flex items-start gap-3 lg:flex-1">
									<input type="checkbox" class="mt-1 h-4 w-4 rounded border-border" checked={item.status === 'done'} onchange={() => toggleComplete(item)} />
									<div class="min-w-0">
										<div class="flex flex-wrap items-center gap-2">
											<h3 class="font-semibold {item.status === 'done' ? 'text-muted-foreground line-through' : 'text-foreground'}">{item.title}</h3>
											<span class="rounded-full px-2 py-0.5 text-xs font-medium {getTrackingStatusClass(item.status)}">{getTrackingStatusLabel(item.status)}</span>
										</div>
										{#if item.description}
											<p class="mt-1 text-sm text-muted-foreground">{item.description}</p>
										{/if}
										<div class="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
											<span>시작가능일: {formatDate(item.start_at)}</span>
											<span>마감기한: {formatDate(item.due_at)}</span>
											{#if item.completed_at}
												<span>완료: {formatDate(item.completed_at)}</span>
											{/if}
											{#if item.linked_plans.length > 0}
												<button
													type="button"
													class="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-primary hover:bg-primary/20"
													aria-expanded={expandedPlansItemId === item.id}
													aria-controls={`tracking-plan-actions-${item.id}`}
													onclick={(event) => {
														stopPlanAction(event);
														togglePlanActions(item.id);
													}}
												>
													계획서 {item.linked_plans.length}건
													<ChevronDown size={12} class="transition-transform {expandedPlansItemId === item.id ? 'rotate-180' : ''}" />
												</button>
											{/if}
										</div>
									</div>
								</div>
								<div class="flex gap-2 lg:justify-end">
									<button class="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted" onclick={() => openEditModal(item)}>수정</button>
									<button class="rounded-md border border-destructive/30 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10" onclick={() => deleteItem(item)}>삭제</button>
								</div>
							</div>
							{#if expandedPlansItemId === item.id && item.linked_plans.length > 0}
								<div id={`tracking-plan-actions-${item.id}`} class="mt-3 rounded-xl border border-border bg-muted/20 p-3">
									<div class="space-y-2">
										{#each item.linked_plans as plan}
											{@const disabledReason = getPlanActionDisabledReason(plan)}
											<div class="flex flex-col gap-2 rounded-lg bg-background px-3 py-2 text-xs sm:flex-row sm:items-center sm:justify-between">
												<div class="min-w-0">
													<div class="flex flex-wrap items-center gap-2">
														<span class="truncate font-medium text-foreground" title={plan.file_path}>{getPlanDisplayName(plan)}</span>
														{#if plan.archived}<span class="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">archived</span>{/if}
														{#if plan.file_removed}<span class="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">파일 없음</span>{/if}
													</div>
													<div class="mt-0.5 truncate font-mono text-muted-foreground" title={plan.file_path}>{plan.file_path}</div>
												</div>
												<div class="flex shrink-0 flex-wrap gap-1">
													<button
														type="button"
														class="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
														disabled={Boolean(disabledReason)}
														onclick={() => handleCopyPlanPath(plan)}
														title={disabledReason ?? '계획서 경로 복사'}
													>
														<Copy size={13} /> 복사
													</button>
													<button
														type="button"
														class="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
														disabled={Boolean(disabledReason)}
														onclick={() => handleOpenPlanInEditor(plan)}
														title={disabledReason ?? 'VSCode에서 열기'}
													>
														<ExternalLink size={13} /> 열기
													</button>
													<button
														type="button"
														class="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
														disabled={Boolean(disabledReason)}
														onclick={() => handleOpenPlanInExplorer(plan)}
														title={disabledReason ?? '계획서 폴더 경로 복사'}
													>
														<FolderOpen size={13} /> 폴더
													</button>
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						</article>
					{/each}
				</div>
			{/if}
		</section>
	</div>
</div>

{#if showModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
		role="dialog"
		aria-modal="true"
		tabindex="-1"
		onclick={(e) => { if (e.target === e.currentTarget && !saving) showModal = false; }}
		onkeydown={(e) => { if (e.key === 'Escape' && !saving) showModal = false; }}
	>
		<div class="w-full max-w-xl rounded-2xl border border-border bg-card p-5 shadow-xl">
			<div class="mb-4 flex items-start justify-between gap-3">
				<div>
					<h3 class="text-lg font-bold">{editingItem ? 'Tracking 항목 수정' : 'Tracking 항목 추가'}</h3>
					<p class="mt-1 text-sm text-muted-foreground">시작가능일 또는 마감기한 중 하나 이상은 필수입니다.</p>
				</div>
				<button class="rounded-md px-2 py-1 text-muted-foreground hover:bg-muted" onclick={() => (showModal = false)} disabled={saving}>닫기</button>
			</div>

			<div class="space-y-4">
				<label class="block">
					<span class="text-sm font-medium">제목</span>
					<input class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm" bind:value={form.title} />
				</label>
				<label class="block">
					<span class="text-sm font-medium">설명</span>
					<textarea class="mt-1 min-h-24 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm" bind:value={form.description}></textarea>
				</label>
				<div class="grid gap-4 sm:grid-cols-2">
					<label class="block">
						<span class="text-sm font-medium">시작가능일</span>
						<input type="datetime-local" class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm" bind:value={form.start_at} />
					</label>
					<label class="block">
						<span class="text-sm font-medium">마감기한</span>
						<input type="datetime-local" class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm" bind:value={form.due_at} />
					</label>
				</div>
				<!-- 연결된 계획서 섹션 -->
				<div class="space-y-2">
					<div class="text-sm font-medium">연결된 계획서</div>
					{#if editingItem && editingItem.linked_plans.length > 0}
						<div class="space-y-2">
							{#each editingItem.linked_plans as lp}
								{@const disabledReason = getPlanActionDisabledReason(lp)}
								<div class="rounded-lg bg-muted px-3 py-2 text-xs">
									<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
										<div class="min-w-0">
											<div class="flex flex-wrap items-center gap-1">
												<span class="max-w-64 truncate font-medium" title={lp.file_path}>{getPlanDisplayName(lp)}</span>
												{#if lp.archived}<span class="text-amber-600">archived</span>{/if}
												{#if lp.file_removed}<span class="text-muted-foreground">(파일 없음)</span>{/if}
											</div>
											<div class="mt-0.5 truncate font-mono text-muted-foreground" title={lp.file_path}>{lp.file_path}</div>
										</div>
										<div class="flex shrink-0 flex-wrap gap-1">
											<button
												type="button"
												class="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
												disabled={Boolean(disabledReason)}
												onclick={() => handleCopyPlanPath(lp)}
												title={disabledReason ?? '계획서 경로 복사'}
											>
												<Copy size={13} /> 복사
											</button>
											<button
												type="button"
												class="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
												disabled={Boolean(disabledReason)}
												onclick={() => handleOpenPlanInEditor(lp)}
												title={disabledReason ?? 'VSCode에서 열기'}
											>
												<ExternalLink size={13} /> 열기
											</button>
											<button
												type="button"
												class="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
												disabled={Boolean(disabledReason)}
												onclick={() => handleOpenPlanInExplorer(lp)}
												title={disabledReason ?? '계획서 폴더 경로 복사'}
											>
												<FolderOpen size={13} /> 폴더
											</button>
											<button
												type="button"
												class="rounded-md border border-destructive/30 bg-background px-2 py-1 text-destructive hover:bg-destructive/10 disabled:opacity-50"
												disabled={pickerSaving}
												onclick={async () => {
													pickerSaving = true;
													try {
														const updated = await trackingApi.unlinkPlan(editingItem!.id, lp.plan_record_id);
														editingItem = updated;
														const nextItems = items.map((i) => (i.id === updated.id ? updated : i));
														items = sortTrackingItems(nextItems);
														toast.success('계획서 연결을 해제했습니다.');
													} catch {
														toast.error('연결 해제 실패');
													} finally {
														pickerSaving = false;
													}
												}}
												aria-label="연결 해제"
											>해제</button>
										</div>
									</div>
								</div>
							{/each}
						</div>
					{/if}
					<TrackingPlanPicker
						value={pickerValue}
						alreadyLinked={editingItem?.linked_plans ?? []}
						onChange={(ids) => { pickerValue = ids; }}
					/>
				</div>
			</div>

			<div class="mt-6 flex justify-end gap-2">
				<button class="rounded-lg border border-border px-4 py-2 text-sm hover:bg-muted" onclick={() => (showModal = false)} disabled={saving}>취소</button>
				<button class="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50" onclick={saveItem} disabled={saving}>
					{saving ? '저장 중...' : '저장'}
				</button>
			</div>
		</div>
	</div>
{/if}
