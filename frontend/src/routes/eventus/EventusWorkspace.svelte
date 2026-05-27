<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import { Button } from '$lib/components/ui';
	import { buildMonitoringHref } from '$lib/utils/monitoringRouteState';
	import {
		eventusReservationApi,
		type EventusTarget,
		type EventusSchedule,
		type EventusAnalyzeResponse,
		type EventusSlotInfo
	} from '$lib/api/eventusReservation';
	import type { MonitoringEvent } from '$lib/types';
	import { Plus, RefreshCw, Search, X, CalendarCheck } from 'lucide-svelte';
	import {
		parseEventusSlots,
		getOpenSlots,
		getClosedSlots,
		getSlotLabel,
		getSlotStatusText
	} from '$lib/utils/eventusSlotDisplay';

	type ActiveTab = 'schedules' | 'history';

	interface Props {
		view?: string | null;
		sub?: string | null;
		unified?: boolean;
	}

	let { view = null, sub = null, unified = false }: Props = $props();

	function normalizeEventusTab(tab: string | null | undefined): ActiveTab {
		return tab === 'history' ? 'history' : 'schedules';
	}

	let activeTab = $state<ActiveTab>(normalizeEventusTab(view ?? sub));
	let targets = $state<EventusTarget[]>([]);
	let schedules = $state<EventusSchedule[]>([]);
	let historyEvents = $state<MonitoringEvent[]>([]);

	// Analyze form
	let analyzeInput = $state('');
	let analyzeLoading = $state(false);
	let analyzeResult = $state<EventusAnalyzeResponse | null>(null);
	let analyzeError = $state('');

	// Target creation from analyze result
	let selectedBundleId = $state('');
	let selectedTimeKey = $state('');
	let createTargetLoading = $state(false);
	let createTargetError = $state('');

	// Schedule form
	let selectedTargetId = $state('');
	let scheduleDate = $state('');

	let loading = $state(false);
	let error = $state('');
	let historyLoading = $state(false);
	let historyError = $state('');
	let historyLoadedOnce = $state(false);
	let selectedEvent = $state<MonitoringEvent | null>(null);
	let showDetailModal = $state(false);

	let historyPage = $state(1);
	let historyPageSize = $state(30);
	let historyTotal = $state(0);
	let historyTotalPages = $state(1);
	let historyFilters = $state({
		status: '',
		date_from: getTodayDate(),
		date_to: ''
	});

	const eventusTabs = $derived([
		{
			id: 'schedules',
			label: '일정',
			href: unified ? buildMonitoringHref({ type: 'eventus', view: 'schedules' }, $page.url) : undefined
		},
		{
			id: 'history',
			label: '실행내역',
			href: unified ? buildMonitoringHref({ type: 'eventus', view: 'history' }, $page.url) : undefined
		}
	]);
	const fieldClass = 'h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground';

	function getTodayDate(): string {
		return new Date().toISOString().split('T')[0];
	}

	async function load() {
		loading = true;
		error = '';
		try {
			[targets, schedules] = await Promise.all([
				eventusReservationApi.listTargets(),
				eventusReservationApi.listSchedules()
			]);
			if (!selectedTargetId && targets[0]) selectedTargetId = String(targets[0].id);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	async function loadHistory(showLoading = true) {
		if (showLoading) historyLoading = true;
		historyError = '';
		try {
			const result = await eventusReservationApi.listEvents({
				status: historyFilters.status || undefined,
				date_from: historyFilters.date_from || undefined,
				date_to: historyFilters.date_to || undefined,
				page: historyPage,
				page_size: historyPageSize
			} as Parameters<typeof eventusReservationApi.listEvents>[0]);
			historyEvents = result.items ?? [];
			historyTotal = result.total ?? 0;
			historyTotalPages = Math.max(1, Math.ceil(historyTotal / historyPageSize));
			historyLoadedOnce = true;
		} catch (err) {
			historyError = err instanceof Error ? err.message : String(err);
		} finally {
			historyLoading = false;
		}
	}

	async function analyzeEvent() {
		if (!analyzeInput.trim()) return;
		analyzeLoading = true;
		analyzeResult = null;
		analyzeError = '';
		selectedBundleId = '';
		selectedTimeKey = '';
		try {
			analyzeResult = await eventusReservationApi.analyzeEvent({ input: analyzeInput.trim() });
			if (analyzeResult.error_code) {
				analyzeError = analyzeResult.error_message ?? analyzeResult.error_code;
			}
		} catch (err) {
			analyzeError = err instanceof Error ? err.message : String(err);
		} finally {
			analyzeLoading = false;
		}
	}

	async function createTargetFromAnalysis() {
		if (!analyzeResult?.source_url) return;
		createTargetLoading = true;
		createTargetError = '';
		try {
			const created = await eventusReservationApi.createTarget({
				source_url: analyzeResult.source_url,
				event_id: analyzeResult.event_id ?? undefined,
				organizer_slug: analyzeResult.organizer_slug ?? undefined,
				channel_name: analyzeResult.channel_name ?? undefined,
				title: analyzeResult.title ?? undefined,
				bundle_ids: analyzeResult.bundles,
				selected_bundle_id: selectedBundleId || undefined,
				selected_time_key: selectedTimeKey || undefined
			});
			targets = [...targets, created];
			selectedTargetId = String(created.id);
			analyzeResult = null;
			analyzeInput = '';
		} catch (err) {
			createTargetError = err instanceof Error ? err.message : String(err);
		} finally {
			createTargetLoading = false;
		}
	}

	async function addSchedule() {
		if (!selectedTargetId || !scheduleDate) return;
		try {
			await eventusReservationApi.createSchedules({
				biz_item_id: parseInt(selectedTargetId),
				dates: [scheduleDate]
			});
			scheduleDate = '';
			await load();
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		}
	}

	async function toggleSchedule(s: EventusSchedule) {
		try {
			if (s.is_enabled) {
				await eventusReservationApi.disableSchedule(s.id);
			} else {
				await eventusReservationApi.enableSchedule(s.id);
			}
			await load();
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		}
	}

	async function checkNow(s: EventusSchedule) {
		try {
			await eventusReservationApi.checkNow(s.id);
			await load();
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		}
	}

	async function deleteSchedule(s: EventusSchedule) {
		if (!confirm(`일정 ${s.id} (${s.date})를 삭제하시겠습니까?`)) return;
		try {
			await eventusReservationApi.deleteSchedule(s.id);
			await load();
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		}
	}

	async function deleteTarget(t: EventusTarget) {
		if (!confirm(`대상 "${t.name}"을(를) 삭제하시겠습니까?`)) return;
		try {
			await eventusReservationApi.deleteTarget(t.id);
			await load();
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		}
	}

	function openDetail(event: MonitoringEvent) {
		selectedEvent = event;
		showDetailModal = true;
	}

	function closeDetail() {
		showDetailModal = false;
		selectedEvent = null;
	}

	function statusBadgeClass(status: string): string {
		if (status === 'available' || status === 'slot_detected') return 'bg-green-100 text-green-800';
		if (status === 'no_slots') return 'bg-gray-100 text-gray-600';
		if (status === 'error') return 'bg-red-100 text-red-700';
		return 'bg-blue-100 text-blue-700';
	}

	onMount(load);

	$effect(() => {
		if (unified) activeTab = normalizeEventusTab(view ?? sub);
		if (activeTab === 'history' && !historyLoadedOnce) {
			loadHistory();
		}
	});

	$effect(() => {
		if (!unified || view !== 'create') return;
		goto(buildMonitoringHref({ type: 'eventus', view: 'schedules' }, $page.url), {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	});
</script>

{#snippet headerActions()}
	<Button variant="ghost" size="icon" onclick={load} title="새로고침">
		<RefreshCw class="h-4 w-4" />
	</Button>
{/snippet}

<TabbedPageLayout
	title="이벤터스 잔여석 모니터링"
	primaryTabs={eventusTabs}
	bind:activePrimaryTab={activeTab}
	primaryQueryParam={unified ? undefined : 'tab'}
	primaryUrlBased={unified}
	actions={headerActions}
>

	<!-- ─── 일정 탭 ──────────────────────────────────────────── -->
	{#if activeTab === 'schedules'}
		<div class="space-y-6 p-4">

			<!-- 이벤터스 URL/event_id 분석 -->
			<div class="rounded-lg border p-4 space-y-3">
				<h3 class="font-semibold text-sm">이벤터스 이벤트 분석</h3>
				<div class="flex gap-2">
					<input
						class="{fieldClass} flex-1"
						type="text"
						placeholder="URL 또는 event_id 입력 (예: https://event-us.kr/.../event/126341)"
						bind:value={analyzeInput}
						on:keydown={(e) => e.key === 'Enter' && analyzeEvent()}
					/>
					<Button onclick={analyzeEvent} disabled={analyzeLoading || !analyzeInput.trim()}>
						{#if analyzeLoading}
							<RefreshCw class="h-4 w-4 animate-spin mr-1" />분석 중...
						{:else}
							<Search class="h-4 w-4 mr-1" />분석
						{/if}
					</Button>
				</div>

				{#if analyzeError}
					<p class="text-sm text-red-600">{analyzeError}</p>
				{/if}

				{#if analyzeResult && !analyzeResult.error_code}
					<div class="rounded border bg-muted/30 p-3 space-y-2 text-sm">
						<p><strong>제목:</strong> {analyzeResult.title ?? '—'}</p>
						<p><strong>채널/업체:</strong> {analyzeResult.channel_name ?? analyzeResult.organizer_slug ?? '—'}</p>
						<p><strong>event_id:</strong> {analyzeResult.event_id ?? '—'}</p>
						<p><strong>bundle 수:</strong> {analyzeResult.bundles.length}개 — {analyzeResult.slots.length}개 슬롯 감지 (마감 {analyzeResult.closed_token_counts}건)</p>

						{#if analyzeResult.bundles.length > 0}
							<div class="space-y-1">
								<p class="font-medium">Bundle 선택 (감시 대상):</p>
								<select class="{fieldClass} w-full" bind:value={selectedBundleId}>
									<option value="">전체 (필터 없음)</option>
									{#each analyzeResult.bundles as bid}
										<option value={bid}>{bid}</option>
									{/each}
								</select>
							</div>
						{/if}

						{#if selectedBundleId}
							{@const bundleSlots = analyzeResult.slots.filter(s => s.bundle_id === selectedBundleId)}
							{#if bundleSlots.length > 0}
								<div class="space-y-1">
									<p class="font-medium">시간대 선택 (감시 대상):</p>
									<select class="{fieldClass} w-full" bind:value={selectedTimeKey}>
										<option value="">전체 시간대</option>
										{#each bundleSlots as slot}
											<option value={slot.time_label ?? ''}>
												{slot.time_label ?? '시간 미확인'}
												{slot.is_closed ? ' [마감]' : slot.urgency_hint === 'imminent' ? ' [마감임박]' : ''}
											</option>
										{/each}
									</select>
								</div>
							{/if}
						{/if}

						{#if createTargetError}
							<p class="text-sm text-red-600">{createTargetError}</p>
						{/if}
						<Button onclick={createTargetFromAnalysis} disabled={createTargetLoading}>
							{#if createTargetLoading}
								<RefreshCw class="h-4 w-4 animate-spin mr-1" />저장 중...
							{:else}
								<Plus class="h-4 w-4 mr-1" />대상 저장
							{/if}
						</Button>
					</div>
				{/if}
			</div>

			<!-- 대상 목록 -->
			{#if targets.length > 0}
				<div class="rounded-lg border p-4 space-y-2">
					<h3 class="font-semibold text-sm">등록된 대상</h3>
					<div class="space-y-2">
						{#each targets as t (t.id)}
							<div class="flex items-center justify-between gap-2 rounded border p-2 text-sm">
								<div class="flex-1 min-w-0">
									<p class="font-medium truncate">{t.name}</p>
									<p class="text-xs text-muted-foreground truncate">
										{t.event_id ?? ''} · {t.channel_name ?? t.organizer_slug ?? ''}
										{t.selected_bundle_id ? ` · ${t.selected_bundle_id}` : ''}
										{t.selected_time_key ? ` · ${t.selected_time_key}` : ''}
									</p>
								</div>
								<Button variant="ghost" size="icon" onclick={() => deleteTarget(t)} title="삭제">
									<X class="h-4 w-4" />
								</Button>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- 일정 추가 -->
			<div class="rounded-lg border p-4 space-y-3">
				<h3 class="font-semibold text-sm">일정 추가</h3>
				<div class="flex gap-2 flex-wrap">
					<select class="{fieldClass} flex-1" bind:value={selectedTargetId}>
						<option value="">대상 선택</option>
						{#each targets as t (t.id)}
							<option value={String(t.id)}>{t.name}</option>
						{/each}
					</select>
					<input class="{fieldClass}" type="date" bind:value={scheduleDate} />
					<Button
						onclick={addSchedule}
						disabled={!selectedTargetId || !scheduleDate}
					>
						<Plus class="h-4 w-4 mr-1" />추가
					</Button>
				</div>
			</div>

			{#if error}
				<p class="text-sm text-red-600">{error}</p>
			{/if}

			<!-- 일정 목록 -->
			{#if loading}
				<p class="text-sm text-muted-foreground">로딩 중...</p>
			{:else if schedules.length === 0}
				<p class="text-sm text-muted-foreground">등록된 일정이 없습니다.</p>
			{:else}
				<div class="overflow-x-auto rounded-lg border">
					<table class="w-full text-sm">
						<thead class="bg-muted/50">
							<tr>
								<th class="px-3 py-2 text-left">ID</th>
								<th class="px-3 py-2 text-left">이름</th>
								<th class="px-3 py-2 text-left">날짜</th>
								<th class="px-3 py-2 text-left">상태</th>
								<th class="px-3 py-2 text-left">최근 확인</th>
								<th class="px-3 py-2 text-left">최근 결과</th>
								<th class="px-3 py-2 text-left">액션</th>
							</tr>
						</thead>
						<tbody>
							{#each schedules as s (s.id)}
								<tr class="border-t hover:bg-muted/20">
									<td class="px-3 py-2">{s.id}</td>
									<td class="px-3 py-2">{s.item_name ?? '—'}</td>
									<td class="px-3 py-2">{s.date}</td>
									<td class="px-3 py-2">
										<span class="rounded px-1.5 py-0.5 text-xs {s.is_enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}">
											{s.is_enabled ? '활성' : '비활성'}
										</span>
									</td>
									<td class="px-3 py-2 text-xs text-muted-foreground">
										{s.last_check_time ? s.last_check_time.slice(0, 16).replace('T', ' ') : '—'}
									</td>
									<td class="px-3 py-2">
										{#if s.last_event_status}
											<span class="rounded px-1.5 py-0.5 text-xs {statusBadgeClass(s.last_event_status)}">
												{s.last_event_status}
											</span>
										{:else}
											<span class="text-muted-foreground text-xs">—</span>
										{/if}
									</td>
									<td class="px-3 py-2">
										<div class="flex gap-1">
											<Button variant="outline" size="sm" onclick={() => toggleSchedule(s)}>
												{s.is_enabled ? '중지' : '시작'}
											</Button>
											<Button variant="outline" size="sm" onclick={() => checkNow(s)}>
												확인
											</Button>
											<Button variant="ghost" size="icon" onclick={() => deleteSchedule(s)}>
												<X class="h-3 w-3" />
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
	{/if}

	<!-- ─── 실행내역 탭 ─────────────────────────────────────── -->
	{#if activeTab === 'history'}
		<div class="space-y-4 p-4">
			<!-- 필터 -->
			<div class="flex gap-2 flex-wrap">
				<select class="{fieldClass}" bind:value={historyFilters.status}
					on:change={() => { historyPage = 1; loadHistory(); }}>
					<option value="">전체 상태</option>
					<option value="available">available</option>
					<option value="no_slots">no_slots</option>
					<option value="error">error</option>
				</select>
				<input class="{fieldClass}" type="date" bind:value={historyFilters.date_from}
					on:change={() => { historyPage = 1; loadHistory(); }} />
				<input class="{fieldClass}" type="date" bind:value={historyFilters.date_to}
					on:change={() => { historyPage = 1; loadHistory(); }} />
				<Button variant="ghost" size="icon" onclick={() => loadHistory()}>
					<RefreshCw class="h-4 w-4" />
				</Button>
			</div>

			{#if historyError}
				<p class="text-sm text-red-600">{historyError}</p>
			{/if}

			{#if historyLoading}
				<p class="text-sm text-muted-foreground">로딩 중...</p>
			{:else if !historyLoadedOnce}
				<p class="text-sm text-muted-foreground">실행내역 탭을 클릭하면 불러옵니다.</p>
			{:else if historyEvents.length === 0}
				<p class="text-sm text-muted-foreground">이력이 없습니다.</p>
			{:else}
				<div class="space-y-3 md:hidden">
					{#each historyEvents as evt (evt.id)}
						{@const evtSlots = parseEventusSlots(evt.slots_info ?? [])}
						{@const evtOpen = getOpenSlots(evtSlots)}
						<article class="rounded-lg border bg-card p-3 text-sm shadow-sm">
							<div class="flex items-start justify-between gap-3">
								<div class="min-w-0">
									<p class="truncate font-medium text-foreground">이벤트 #{evt.id}</p>
									<p class="mt-1 text-xs text-muted-foreground">
										{evt.timestamp?.slice(0, 16).replace('T', ' ') ?? '시각 없음'}
									</p>
								</div>
								<span class="shrink-0 rounded px-1.5 py-0.5 text-xs {statusBadgeClass(evt.status)}">
									{evt.status}
								</span>
							</div>
							<dl class="mt-3 grid grid-cols-2 gap-2 text-xs">
								<div>
									<dt class="text-muted-foreground">일정 ID</dt>
									<dd class="mt-0.5 font-medium text-foreground">{evt.schedule_id}</dd>
								</div>
								<div>
									<dt class="text-muted-foreground">감지된 열린 옵션</dt>
									<dd class="mt-0.5 font-medium text-foreground">{evtOpen.length}개</dd>
								</div>
							</dl>
							<div class="mt-3 rounded-md bg-muted/40 p-2 text-xs">
								<p class="mb-1 font-medium text-foreground">열린 옵션</p>
								{#if evtSlots.length === 0}
									<p class="text-muted-foreground">시간대 정보 없음</p>
								{:else if evtOpen.length === 0}
									<p class="text-muted-foreground">열린 옵션 없음</p>
								{:else}
									<p class="text-foreground">
										{#if evtOpen.length === 1}
											{getSlotLabel(evtOpen[0])}
										{:else if evtOpen.length === 2}
											{getSlotLabel(evtOpen[0])}, {getSlotLabel(evtOpen[1])}
										{:else}
											{getSlotLabel(evtOpen[0])}, {getSlotLabel(evtOpen[1])} 외 {evtOpen.length - 2}개
										{/if}
									</p>
								{/if}
							</div>
							<div class="mt-3 flex justify-end">
								<Button variant="outline" size="sm" onclick={() => openDetail(evt)}>보기</Button>
							</div>
						</article>
					{/each}
				</div>

				<div class="hidden overflow-x-auto rounded-lg border md:block">
					<table class="w-full text-sm">
						<thead class="bg-muted/50">
							<tr>
								<th class="px-3 py-2 text-left">ID</th>
								<th class="px-3 py-2 text-left">시각</th>
								<th class="px-3 py-2 text-left">상태</th>
								<th class="px-3 py-2 text-left">열린 옵션</th>
								<th class="px-3 py-2 text-left">일정 ID</th>
								<th class="px-3 py-2 text-left">상세</th>
							</tr>
						</thead>
						<tbody>
							{#each historyEvents as evt (evt.id)}
								{@const evtSlots = parseEventusSlots(evt.slots_info ?? [])}
								{@const evtOpen = getOpenSlots(evtSlots)}
								<tr class="border-t hover:bg-muted/20">
									<td class="px-3 py-2">{evt.id}</td>
									<td class="px-3 py-2 text-xs">{evt.timestamp?.slice(0, 16).replace('T', ' ') ?? '—'}</td>
									<td class="px-3 py-2">
										<span class="rounded px-1.5 py-0.5 text-xs {statusBadgeClass(evt.status)}">
											{evt.status}
										</span>
									</td>
									<td class="px-3 py-2">
										{#if evtSlots.length === 0}
											<span class="text-muted-foreground text-xs">시간대 정보 없음</span>
										{:else if evtOpen.length === 0}
											<span class="text-muted-foreground text-xs">열린 옵션 없음</span>
										{:else}
											<span class="text-xs">
												{#if evtOpen.length === 1}
													{getSlotLabel(evtOpen[0])}{#if evtOpen[0].urgencyHint === 'imminent'} <span class="rounded bg-orange-100 px-1 py-0.5 text-orange-700">마감임박</span>{/if}
												{:else if evtOpen.length === 2}
													{getSlotLabel(evtOpen[0])}, {getSlotLabel(evtOpen[1])}
												{:else}
													{getSlotLabel(evtOpen[0])}, {getSlotLabel(evtOpen[1])} 외 {evtOpen.length - 2}개
												{/if}
											</span>
										{/if}
									</td>
									<td class="px-3 py-2">{evt.schedule_id}</td>
									<td class="px-3 py-2">
										<Button variant="ghost" size="sm" onclick={() => openDetail(evt)}>보기</Button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- 페이지네이션 -->
				{#if historyTotalPages > 1}
					<div class="flex items-center gap-2 text-sm">
						<Button variant="outline" size="sm" disabled={historyPage <= 1}
							onclick={() => { historyPage--; loadHistory(); }}>이전</Button>
						<span>{historyPage} / {historyTotalPages} (총 {historyTotal}건)</span>
						<Button variant="outline" size="sm" disabled={historyPage >= historyTotalPages}
							onclick={() => { historyPage++; loadHistory(); }}>다음</Button>
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</TabbedPageLayout>

<!-- ─── Detail Modal ──────────────────────────────────────────── -->
{#if showDetailModal && selectedEvent}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" on:click={closeDetail}>
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div class="bg-background rounded-lg shadow-lg max-w-lg w-full mx-4 p-4 space-y-3" on:click|stopPropagation>
			<div class="flex items-center justify-between">
				<h3 class="font-semibold">이벤트 상세 #{selectedEvent.id}</h3>
				<Button variant="ghost" size="icon" onclick={closeDetail}><X class="h-4 w-4" /></Button>
			</div>
			<dl class="text-sm space-y-1">
				<div class="flex gap-2"><dt class="font-medium w-24">상태:</dt><dd>{selectedEvent.status}</dd></div>
				<div class="flex gap-2"><dt class="font-medium w-24">시각:</dt><dd>{selectedEvent.timestamp}</dd></div>
				<div class="flex gap-2"><dt class="font-medium w-24">일정 ID:</dt><dd>{selectedEvent.schedule_id}</dd></div>
			</dl>
			{#if selectedEvent.slots_info && selectedEvent.slots_info.length > 0}
				{@const modalSlots = parseEventusSlots(selectedEvent.slots_info)}
				{@const modalOpen = getOpenSlots(modalSlots)}
				{@const modalClosed = getClosedSlots(modalSlots)}
				<div>
					<p class="font-medium text-sm mb-1">감지된 열린 옵션 <span class="text-muted-foreground font-normal">({modalOpen.length}개)</span></p>
					{#if modalOpen.length === 0}
						<p class="text-xs text-muted-foreground">열린 옵션 없음</p>
					{:else}
						<table class="w-full text-xs border rounded mb-2">
							<thead class="bg-muted/50">
								<tr>
									<th class="px-2 py-1 text-left">시간대</th>
									<th class="px-2 py-1 text-left">상태</th>
								</tr>
							</thead>
							<tbody>
								{#each modalOpen as slot, slotIdx (slotIdx)}
									<tr class="border-t">
										<td class="px-2 py-1">{getSlotLabel(slot)}</td>
										<td class="px-2 py-1">
											{#if slot.urgencyHint === 'imminent'}
												<span class="rounded bg-orange-100 px-1 py-0.5 text-orange-700">마감임박</span>
											{:else}
												<span class="text-green-700">{getSlotStatusText(slot)}</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
					{#if modalClosed.length > 0}
						<details class="text-xs">
							<summary class="cursor-pointer text-muted-foreground mb-1">마감 옵션 {modalClosed.length}개 보기</summary>
							<table class="w-full border rounded mt-1">
								<thead class="bg-muted/50">
									<tr>
										<th class="px-2 py-1 text-left">시간대</th>
										<th class="px-2 py-1 text-left">사유</th>
									</tr>
								</thead>
								<tbody>
									{#each modalClosed as slot, slotIdx (slotIdx)}
										<tr class="border-t">
											<td class="px-2 py-1">{getSlotLabel(slot)}</td>
											<td class="px-2 py-1 text-muted-foreground">{slot.closedText ?? '마감'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</details>
					{/if}
				</div>
				<details class="text-xs">
					<summary class="cursor-pointer text-muted-foreground">원시 슬롯 데이터 보기</summary>
					<pre class="text-xs bg-muted rounded p-2 overflow-auto max-h-48 mt-1">{JSON.stringify(selectedEvent.slots_info, null, 2)}</pre>
				</details>
			{:else if selectedEvent.slots_info !== null && selectedEvent.slots_info !== undefined}
				<p class="text-xs text-muted-foreground">슬롯 정보 없음</p>
			{/if}
		</div>
	</div>
{/if}
