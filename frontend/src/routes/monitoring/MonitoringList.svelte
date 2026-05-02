<script lang="ts">
	import type { UnifiedMonitorItem } from '$lib/types/monitoring';
	import { MONITOR_TYPE_META } from '$lib/types/monitoring';
	import { iconMap, type IconName } from '$lib/iconMap';
	import { goto } from '$app/navigation';

	interface Props {
		items: UnifiedMonitorItem[];
		onToggle: (item: UnifiedMonitorItem) => void;
	}

	let { items, onToggle }: Props = $props();

	const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
		running: { label: '실행중', cls: 'bg-green-100 text-green-700' },
		idle: { label: '대기', cls: 'bg-gray-100 text-gray-600' },
		error: { label: '오류', cls: 'bg-red-100 text-red-700' },
		disabled: { label: '비활성', cls: 'bg-yellow-100 text-yellow-700' }
	};

	function handleRowClick(item: UnifiedMonitorItem) {
		goto(item.detailHref);
	}

	function handleToggleClick(e: MouseEvent, item: UnifiedMonitorItem) {
		e.stopPropagation();
		onToggle(item);
	}
</script>

<div class="overflow-x-auto rounded-lg border border-border">
	<table class="w-full text-sm">
		<thead class="bg-muted/50 text-muted-foreground">
			<tr>
				<th class="px-4 py-3 text-left font-medium">이름</th>
				<th class="px-4 py-3 text-left font-medium">유형</th>
				<th class="px-4 py-3 text-left font-medium">상태</th>
				<th class="px-4 py-3 text-left font-medium">요약</th>
				<th class="px-4 py-3 text-left font-medium">마지막 확인</th>
				<th class="px-4 py-3 text-center font-medium">활성</th>
			</tr>
		</thead>
		<tbody class="divide-y divide-border">
			{#each items as item (item.id)}
				{@const meta = MONITOR_TYPE_META[item.type]}
				{@const TypeIcon = iconMap[meta.icon as IconName]}
				{@const statusInfo = STATUS_LABELS[item.status] ?? STATUS_LABELS.idle}
				<tr
					class="cursor-pointer transition-colors hover:bg-muted/30"
					onclick={() => handleRowClick(item)}
				>
					<td class="px-4 py-3 font-medium">{item.name}</td>
					<td class="px-4 py-3">
						<span class="inline-flex items-center gap-1 text-xs {meta.color}">
							<svelte:component this={TypeIcon} size={14} class={meta.color} />
							{meta.label}
						</span>
					</td>
					<td class="px-4 py-3">
						<span class="inline-block rounded-full px-2 py-0.5 text-xs {statusInfo.cls}">
							{statusInfo.label}
						</span>
					</td>
					<td class="px-4 py-3 text-muted-foreground">{item.summary ?? '-'}</td>
					<td class="px-4 py-3 text-muted-foreground"
						>{item.lastChecked ? item.lastChecked.slice(0, 16).replace('T', ' ') : '-'}</td
					>
					<td class="px-4 py-3 text-center">
						{#if item.toggleable}
							<button
								type="button"
								onclick={(e) => handleToggleClick(e, item)}
								class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none {item.status !== 'disabled'
									? 'bg-primary'
									: 'bg-muted'}"
								aria-label="{item.name} 토글"
							>
								<span
									class="inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform {item.status !==
									'disabled'
										? 'translate-x-4'
										: 'translate-x-0.5'}"
								></span>
							</button>
						{:else}
							<span class="text-xs text-muted-foreground">-</span>
						{/if}
					</td>
				</tr>
			{/each}
			{#if items.length === 0}
				<tr>
					<td colspan="6" class="px-4 py-8 text-center text-muted-foreground"> 항목이 없습니다. </td>
				</tr>
			{/if}
		</tbody>
	</table>
</div>
