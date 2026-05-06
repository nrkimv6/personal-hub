<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { fetchAllMonitorItems, toggleMonitorItem } from '$lib/api/monitoringUnified';
	import type { UnifiedMonitorItem } from '$lib/types/monitoring';
	import type { MonitorType, MonitorStatus } from '$lib/types/monitoring';
	import { MONITOR_TYPE_META } from '$lib/types/monitoring';
	import { toast } from '$lib/stores/toast';
	import MonitoringList from './MonitoringList.svelte';
	import NewMonitorTypeSelector from './NewMonitorTypeSelector.svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';

	// ─── 상태 ────────────────────────────────────────────────────

	let loading = $state(true);
	let items: UnifiedMonitorItem[] = $state([]);
	let errors: { module: string; message: string }[] = $state([]);

	let selectedType: MonitorType | null = $state(null);
	let selectedStatus: MonitorStatus | null = $state(null);
	let showTypeSelector = $state(false);

	let pollTimer: ReturnType<typeof setInterval> | null = null;

	// ─── URL 파라미터 동기화 ──────────────────────────────────────

	$effect(() => {
		const url = $page.url;
		selectedType = (url.searchParams.get('type') as MonitorType) || null;
		selectedStatus = (url.searchParams.get('status') as MonitorStatus) || null;
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
		const result = await fetchAllMonitorItems(selectedType ? [selectedType] : undefined);
		items = result.items;
		errors = result.errors;
		loading = false;
	}

	// ─── 필터 변경 ───────────────────────────────────────────────

	function setTypeFilter(type: MonitorType | null) {
		const url = new URL($page.url);
		if (type) {
			url.searchParams.set('type', type);
		} else {
			url.searchParams.delete('type');
		}
		goto(url.toString(), { replaceState: true });
	}

	function setStatusFilter(status: MonitorStatus | null) {
		const url = new URL($page.url);
		if (status) {
			url.searchParams.set('status', status);
		} else {
			url.searchParams.delete('status');
		}
		goto(url.toString(), { replaceState: true });
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

	const TYPE_ENTRIES = Object.entries(MONITOR_TYPE_META) as [
		MonitorType,
		(typeof MONITOR_TYPE_META)[MonitorType]
	][];

	const STATUS_OPTIONS: { value: MonitorStatus; label: string }[] = [
		{ value: 'running', label: '실행중' },
		{ value: 'idle', label: '대기' },
		{ value: 'error', label: '오류' },
		{ value: 'disabled', label: '비활성' }
	];
</script>

<svelte:head>
	<title>통합 모니터링</title>
</svelte:head>

<PageHeader title="통합 모니터링" density="compact">
	<button
		type="button"
		class="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
		onclick={() => (showTypeSelector = true)}
	>
		+ 새 모니터링 추가
	</button>
</PageHeader>

<main class="mx-auto max-w-6xl space-y-4 p-4">
	<!-- 에러 배너 -->
	{#if errors.length > 0}
		<div class="rounded-lg border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
			<strong>일부 모듈 로드 실패:</strong>
			{errors.map((e) => `${e.module}(${e.message})`).join(', ')}
		</div>
	{/if}

	<!-- 툴바: 타입 필터 + 상태 필터 -->
	<div class="flex flex-wrap gap-2">
		<button
			type="button"
			class="rounded-full px-3 py-1 text-xs transition-colors {selectedType === null
				? 'bg-primary text-primary-foreground'
				: 'bg-muted text-muted-foreground hover:bg-muted/80'}"
			onclick={() => setTypeFilter(null)}
		>
			전체
		</button>
		{#each TYPE_ENTRIES as [type, meta]}
			<button
				type="button"
				class="rounded-full px-3 py-1 text-xs transition-colors {selectedType === type
					? 'bg-primary text-primary-foreground'
					: 'bg-muted text-muted-foreground hover:bg-muted/80'}"
				onclick={() => setTypeFilter(selectedType === type ? null : type)}
			>
				{meta.label}
			</button>
		{/each}
	</div>
	<div class="flex flex-wrap gap-2">
		<button
			type="button"
			class="rounded-full px-3 py-1 text-xs transition-colors {selectedStatus === null
				? 'bg-secondary text-secondary-foreground'
				: 'bg-muted text-muted-foreground hover:bg-muted/80'}"
			onclick={() => setStatusFilter(null)}
		>
			모든 상태
		</button>
		{#each STATUS_OPTIONS as opt}
			<button
				type="button"
				class="rounded-full px-3 py-1 text-xs transition-colors {selectedStatus === opt.value
					? 'bg-secondary text-secondary-foreground'
					: 'bg-muted text-muted-foreground hover:bg-muted/80'}"
				onclick={() => setStatusFilter(selectedStatus === opt.value ? null : opt.value)}
			>
				{opt.label}
			</button>
		{/each}
	</div>

	<!-- 목록 -->
	{#if loading}
		<div class="py-16 text-center text-muted-foreground">로딩 중...</div>
	{:else}
		<MonitoringList items={filteredItems} onToggle={handleToggle} />
	{/if}
</main>

<NewMonitorTypeSelector open={showTypeSelector} onClose={() => (showTypeSelector = false)} />
