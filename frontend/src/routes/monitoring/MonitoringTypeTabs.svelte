<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import TabNav, { type TabItem } from '$lib/components/layout/TabNav.svelte';
	import { MONITOR_TYPE_META, type MonitorType } from '$lib/types/monitoring';
	import { buildMonitoringHref } from '$lib/utils/monitoringRouteState';

	interface Props {
		selectedType: MonitorType | null;
	}

	let { selectedType }: Props = $props();

	const typeTabs: TabItem[] = [
		{ id: 'all', label: '전체' },
		...(Object.entries(MONITOR_TYPE_META) as [MonitorType, (typeof MONITOR_TYPE_META)[MonitorType]][]).map(
			([type, meta]) => ({ id: type, label: meta.label })
		)
	];

	let activeTab = $derived(selectedType ?? 'all');

	function handleTabChange(tab: string) {
		const type = tab === 'all' ? null : (tab as MonitorType);
		goto(buildMonitoringHref({ type, view: type ? MONITOR_TYPE_META[type].defaultView : 'list' }, $page.url), {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}
</script>

<TabNav
	tabs={typeTabs}
	activeTab={activeTab}
	variant="primary"
	level="primary"
	size="compact"
	overflow="scroll"
	onTabChange={handleTabChange}
/>
