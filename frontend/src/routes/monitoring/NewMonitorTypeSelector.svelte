<script lang="ts">
	import { MONITOR_TYPE_META } from '$lib/types/monitoring';
	import type { MonitorType } from '$lib/types/monitoring';
	import { iconMap, type IconName } from '$lib/iconMap';
	import { goto } from '$app/navigation';

	interface Props {
		open: boolean;
		onClose: () => void;
	}

	let { open, onClose }: Props = $props();

	const types = Object.entries(MONITOR_TYPE_META) as [MonitorType, (typeof MONITOR_TYPE_META)[MonitorType]][];

	function handleSelect(href: string) {
		onClose();
		goto(href);
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) onClose();
	}
</script>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
		onclick={handleBackdropClick}
	>
		<div class="w-full max-w-sm rounded-xl border border-border bg-background p-6 shadow-lg">
			<h2 class="mb-4 text-base font-semibold">모니터링 유형 선택</h2>
			<ul class="flex flex-col gap-2">
				{#each types as [type, meta]}
					{@const TypeIcon = iconMap[meta.icon as IconName]}
					<li>
						<button
							type="button"
							class="flex w-full items-center gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:bg-muted/50"
							onclick={() => handleSelect(meta.createHref)}
						>
							<svelte:component this={TypeIcon} size={18} class={meta.color} />
							<span class="text-sm font-medium {meta.color}">{meta.label}</span>
							<span class="ml-auto text-xs text-muted-foreground">→</span>
						</button>
					</li>
				{/each}
			</ul>
			<button
				type="button"
				class="mt-4 w-full rounded-lg py-2 text-sm text-muted-foreground hover:text-foreground"
				onclick={onClose}
			>
				취소
			</button>
		</div>
	</div>
{/if}
