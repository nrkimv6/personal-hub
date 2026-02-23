<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { DevRunnerPlanDetailResponse } from '$lib/api';

	interface Props {
		detail: DevRunnerPlanDetailResponse;
		status: string;
		onClose: () => void;
	}

	let { detail, status, onClose }: Props = $props();

	function statusBadge(s: string): string {
		const map: Record<string, string> = {
			'구현중': 'bg-blue-100 text-blue-700 border border-blue-200',
			'구현완료': 'bg-green-100 text-green-700 border border-green-200',
			'검토완료': 'bg-purple-100 text-purple-700 border border-purple-200',
			'초안': 'bg-gray-100 text-gray-600',
			'보류': 'bg-yellow-100 text-yellow-700 border border-yellow-200'
		};
		return map[s] || 'bg-gray-100 text-gray-600';
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) onClose();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
	}

	onMount(() => {
		document.body.style.overflow = 'hidden';
		document.addEventListener('keydown', handleKeydown);
	});

	onDestroy(() => {
		document.body.style.overflow = '';
		document.removeEventListener('keydown', handleKeydown);
	});
</script>

<!-- Backdrop -->
<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div
	class="fixed inset-0 z-50 bg-black/40 flex items-start sm:items-center justify-center"
	onclick={handleBackdropClick}
>
	<!-- Modal panel -->
	<div
		class="
			relative bg-white flex flex-col
			w-full h-full
			sm:w-full sm:max-w-lg sm:h-auto sm:max-h-[85dvh]
			sm:rounded-xl sm:shadow-xl sm:my-8
		"
	>
		<!-- 고정 헤더 -->
		<div
			class="shrink-0 px-4 pt-4 pb-3 border-b"
			style="padding-top: max(1rem, env(safe-area-inset-top))"
		>
			<div class="flex items-center gap-2 mb-2">
				<span class="text-sm font-semibold truncate flex-1 min-w-0" title={detail.path}>
					{detail.filename}
				</span>
				<span class="text-[10px] px-1.5 py-0.5 rounded shrink-0 {statusBadge(status)}">
					{status}
				</span>
				<button
					class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
					onclick={onClose}
					aria-label="닫기"
				>
					<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
						<line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
					</svg>
				</button>
			</div>

			<!-- 진행률 바 -->
			<div class="flex items-center gap-2">
				<div class="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
					<div
						class="h-full rounded-full transition-all {detail.progress.percent >= 100 ? 'bg-green-500' : 'bg-blue-500'}"
						style="width: {detail.progress.percent}%"
					></div>
				</div>
				<span class="text-[11px] text-gray-500 font-mono shrink-0">
					{detail.progress.done}/{detail.progress.total}
					<span class="text-gray-400">({detail.progress.percent}%)</span>
				</span>
			</div>
		</div>

		<!-- 스크롤 콘텐츠 영역 -->
		<div
			class="flex-1 min-h-0 overflow-y-auto"
			style="padding-bottom: max(1rem, env(safe-area-inset-bottom))"
		>
			{#each detail.phases as phase, i}
				<!-- Phase 섹션 헤더 -->
				<div class="px-4 pt-4 pb-1 flex items-center justify-between">
					<span class="text-xs font-semibold text-gray-700 uppercase tracking-wide">
						{phase.name}
					</span>
					<span class="text-[10px] font-mono text-gray-400 shrink-0">
						{phase.done_count}/{phase.total_count}
					</span>
				</div>

				<!-- Phase 항목 목록 -->
				<div class="px-4 pb-2">
					{#each phase.items as item}
						<div class="flex items-start gap-2.5 min-h-[44px] py-2.5 {item.checked ? 'opacity-50' : ''}">
							{#if item.checked}
								<svg class="w-3.5 h-3.5 shrink-0 text-green-500 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
									<polyline points="20 6 9 17 4 12" />
								</svg>
							{:else}
								<svg class="w-3.5 h-3.5 shrink-0 text-gray-300 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
									<rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
								</svg>
							{/if}
							<span class="text-sm leading-snug {item.checked ? 'line-through text-gray-400' : 'text-gray-800'}">
								{item.text}
							</span>
						</div>

						{#each item.children as child}
							<div class="flex items-start gap-2.5 min-h-[44px] py-2 pl-6 {child.checked ? 'opacity-50' : ''}">
								{#if child.checked}
									<svg class="w-3 h-3 shrink-0 text-green-500 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
										<polyline points="20 6 9 17 4 12" />
									</svg>
								{:else}
									<svg class="w-3 h-3 shrink-0 text-gray-300 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
										<rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
									</svg>
								{/if}
								<span class="text-xs leading-snug {child.checked ? 'line-through text-gray-400' : 'text-gray-600'}">
									{child.text}
								</span>
							</div>
						{/each}
					{/each}
				</div>

				{#if i < detail.phases.length - 1}
					<div class="mx-4 border-t border-gray-100"></div>
				{/if}
			{/each}
		</div>
	</div>
</div>
