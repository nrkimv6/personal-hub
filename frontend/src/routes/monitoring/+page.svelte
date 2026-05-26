<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { fetchAllMonitorItems, toggleMonitorItem } from '$lib/api/monitoringUnified';
	import type { MonitoringRouteState, UnifiedMonitorItem } from '$lib/types/monitoring';
	import type { MonitorType, MonitorStatus } from '$lib/types/monitoring';
	import { MONITOR_TYPE_META } from '$lib/types/monitoring';
	import { buildMonitoringHref, parseMonitoringRouteState } from '$lib/utils/monitoringRouteState';
	import { toast } from '$lib/stores/toast';
	import MonitoringList from './MonitoringList.svelte';
	import MonitoringTypeTabs from './MonitoringTypeTabs.svelte';
	import MonitoringViewTabs from './MonitoringViewTabs.svelte';
	import MonitoringWorkspace from './MonitoringWorkspace.svelte';
	import NewMonitorTypeSelector from './NewMonitorTypeSelector.svelte';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import { Button } from '$lib/components/ui';
	import { Plus } from 'lucide-svelte';

	// ─── 상태 ────────────────────────────────────────────────────

	let loading = $state(true);
	let items: UnifiedMonitorItem[] = $state([]);
	let errors: { module: string; message: string }[] = $state([]);

	let selectedType: MonitorType | null = $state(null);
	let selectedStatus: MonitorStatus | null = $state(null);
	let routeState: MonitoringRouteState = $state({
		type: null,
		view: 'list',
		sub: null,
		id: null,
		status: null
	});
	let showTypeSelector = $state(false);

	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let loadSeq = 0;

	// ─── URL 파라미터 동기화 ──────────────────────────────────────

	$effect(() => {
		routeState = parseMonitoringRouteState($page.url);
		selectedType = routeState.type;
		selectedStatus = routeState.status;
	});

	// ─── 필터링 ──────────────────────────────────────────────────

	const filteredItems = $derived(
		items.filter((item) => {
			if (selectedType && item.type !== selectedType) return false;
			if (selectedStatus && item.status !== selectedStatus) return false;
			return true;
		})
	);

	// ─── 데이터 로드 ─────────────────────────────────────────────

	async function loadData() {
		const seq = ++loadSeq;
		const result = await fetchAllMonitorItems(selectedType ? [selectedType] : undefined);
		if (seq !== loadSeq) return;
		items = result.items;
		errors = result.errors;
		loading = false;
	}

	// ─── 필터 변경 ───────────────────────────────────────────────

	function setStatusFilter(status: MonitorStatus | null) {
		goto(buildMonitoringHref({ status }, $page.url), {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}

	// ─── 토글 ────────────────────────────────────────────────────

	async function handleToggle(item: UnifiedMonitorItem) {
		try {
			await toggleMonitorItem(item);
			// 로컬 상태 즉시 반영
			items = items.map((i) => {
				if (i.id !== item.id) return i;
				return { ...i, status: i.status === 'disabled' ? ('idle' as MonitorStatus) : ('disabled' as MonitorStatus) };
			});
			toast.success(`${item.name} 상태가 변경되었습니다.`);
		} catch {
			toast.error(`${item.name} 상태 변경 실패`);
		}
	}

	// ─── 라이프사이클 ─────────────────────────────────────────────

	onMount(() => {
		loadData();
		pollTimer = setInterval(loadData, 30_000);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	// ─── 상수 ────────────────────────────────────────────────────

	const STATUS_OPTIONS: { value: MonitorStatus; label: string }[] = [
		{ value: 'running', label: '실행중' },
		{ value: 'idle', label: '대기' },
		{ value: 'error', label: '오류' },
		{ value: 'disabled', label: '비활성' }
	];

	const pageTitle = $derived(
		routeState.type
			? `${MONITOR_TYPE_META[routeState.type].label} · ${
					MONITOR_TYPE_META[routeState.type].views.find((entry) => entry.id === routeState.view)?.label ?? '작업면'
				}`
			: '통합 모니터링'
	);
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

{#snippet headerActions()}
	<Button variant="primary" size="sm" onclick={() => (showTypeSelector = true)}>
		<Plus size={16} />
		새 모니터링 추가
	</Button>
{/snippet}

{#snippet filterToolbar()}
	<div class="flex min-w-0 flex-col gap-2">
		<MonitoringTypeTabs selectedType={selectedType} />
		<div class="flex flex-wrap items-center gap-2">
			<button
				type="button"
				class="rounded-full px-3 py-1 text-xs font-medium transition-colors {selectedStatus === null
					? 'bg-secondary text-secondary-foreground'
					: 'bg-muted text-muted-foreground hover:bg-muted/80'}"
				onclick={() => setStatusFilter(null)}
			>
				모든 상태
			</button>
			{#each STATUS_OPTIONS as opt}
				<button
					type="button"
					class="rounded-full px-3 py-1 text-xs font-medium transition-colors {selectedStatus === opt.value
						? 'bg-secondary text-secondary-foreground'
						: 'bg-muted text-muted-foreground hover:bg-muted/80'}"
					onclick={() => setStatusFilter(selectedStatus === opt.value ? null : opt.value)}
				>
					{opt.label}
				</button>
			{/each}
		</div>
		<MonitoringViewTabs type={routeState.type} view={routeState.view} sub={routeState.sub} />
	</div>
{/snippet}

<TabbedPageLayout
	title="통합 모니터링"
	actions={headerActions}
	toolbar={filterToolbar}
	density="compact"
	containerClass="space-y-3 p-4 md:p-6"
>
	<!-- 에러 배너 -->
	{#if errors.length > 0}
		<div class="rounded-lg border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
			<strong>일부 모듈 로드 실패:</strong>
			{errors.map((e) => `${e.module}(${e.message})`).join(', ')}
		</div>
	{/if}

	<!-- 목록 / 작업면 -->
	{#if loading}
		<div class="py-16 text-center text-muted-foreground">로딩 중...</div>
	{:else if routeState.view !== 'list' && routeState.type}
		<MonitoringWorkspace state={routeState} />
	{:else}
		<MonitoringList items={filteredItems} onToggle={handleToggle} />
	{/if}
</TabbedPageLayout>

<NewMonitorTypeSelector open={showTypeSelector} onClose={() => (showTypeSelector = false)} />
