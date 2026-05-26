<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import TabNav, { type TabItem } from '$lib/components/layout/TabNav.svelte';
	import { MONITOR_TYPE_META, type MonitorSubView, type MonitorType, type MonitorView } from '$lib/types/monitoring';
	import { buildMonitoringHref } from '$lib/utils/monitoringRouteState';

	interface Props {
		type: MonitorType | null;
		view: MonitorView;
		sub: MonitorSubView | null;
	}

	let { type, view, sub }: Props = $props();

	const viewTabs = $derived<TabItem[]>(
		type ? MONITOR_TYPE_META[type].views.map((entry) => ({ id: entry.id, label: entry.label })) : []
	);
	const currentViewMeta = $derived(type ? MONITOR_TYPE_META[type].views.find((entry) => entry.id === view) : undefined);
	const subTabs = $derived<TabItem[]>(
		currentViewMeta?.subviews?.map((entry) => ({ id: entry.id, label: entry.label })) ?? []
	);

	function handleViewChange(nextView: string) {
		goto(buildMonitoringHref({ type, view: nextView as MonitorView, sub: null, id: null }, $page.url), {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}

	function handleSubChange(nextSub: string) {
		goto(buildMonitoringHref({ type, view, sub: nextSub as MonitorSubView, id: null }, $page.url), {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}
</script>

{#if type}
	<div class="space-y-2">
		<TabNav
			tabs={viewTabs}
			activeTab={view}
			variant="secondary"
			level="secondary"
			size="compact"
			overflow="scroll"
			onTabChange={handleViewChange}
		/>
		{#if subTabs.length > 0}
			<TabNav
				tabs={subTabs}
				activeTab={sub ?? subTabs[0]?.id}
				variant="secondary"
				level="secondary"
				size="compact"
				overflow="scroll"
				onTabChange={handleSubChange}
			/>
		{/if}
	</div>
{/if}
