<script lang="ts">
	/**
	 * 팝업 모바일 카드 컴포넌트
	 *
	 * 모바일 환경에서 팝업 목록을 카드 형식으로 표시
	 */
	import type { Popup } from '$lib/types';
	import {
		formatDate,
		getEventStatusColor,
		getEventStatusLabel,
		isPopupEndingToday,
		isPopupUnknownPeriod
	} from '$lib/utils/eventUtils';

	interface Props {
		popups: Popup[];
		onPopupClick: (popup: Popup) => void;
		onBookmarkToggle: (popup: Popup, e: MouseEvent) => void;
	}

	let { popups, onPopupClick, onBookmarkToggle }: Props = $props();
</script>

<div class="md:hidden space-y-3 mb-6">
	{#each popups as popup (popup.id)}
		<div
			class="bg-white rounded-lg border border-gray-200 p-3 cursor-pointer hover:shadow-md transition-shadow {isPopupEndingToday(
				popup
			)
				? 'border-orange-300 bg-orange-50'
				: isPopupUnknownPeriod(popup)
					? 'border-amber-200 bg-amber-50'
					: ''}"
			onclick={() => onPopupClick(popup)}
			onkeydown={(e) => e.key === 'Enter' && onPopupClick(popup)}
			role="button"
			tabindex="0"
		>
			<div class="flex justify-between items-start gap-2 mb-2">
				<div class="flex-1 min-w-0">
					<div class="flex items-center gap-2 mb-1">
						<span class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(popup.popup_status)}">
							{getEventStatusLabel(popup.popup_status)}
						</span>
						{#if popup.source_type === 'instagram'}
							<span class="px-1.5 py-0.5 text-xs rounded bg-pink-100 text-pink-600">IG</span>
						{/if}
					</div>
					<h3 class="font-medium text-gray-900 truncate" title={popup.title}>{popup.title}</h3>
					{#if popup.brand || popup.organizer}
						<p class="text-sm text-blue-600 truncate">{popup.brand || popup.organizer}</p>
					{/if}
				</div>
				<!-- 북마크 버튼 -->
				<div class="flex items-center gap-1" onclick={(e) => e.stopPropagation()}>
					<button
						onclick={(e) => onBookmarkToggle(popup, e)}
						class="text-xl transition-colors {popup.is_bookmarked
							? 'text-yellow-500'
							: 'text-gray-300'}"
					>
						{popup.is_bookmarked ? '★' : '☆'}
					</button>
				</div>
			</div>
			<div class="flex flex-wrap items-center gap-2 text-xs text-gray-500">
				<!-- 기간 -->
				{#if popup.end_date}
					{#if isPopupEndingToday(popup)}
						<span class="font-bold text-orange-600 bg-orange-100 px-1.5 py-0.5 rounded"
							>오늘 마감!</span
						>
					{:else}
						<span>~ {formatDate(popup.end_date)}</span>
					{/if}
				{:else}
					<span class="text-amber-600 bg-amber-100 px-1.5 py-0.5 rounded">기간 미정</span>
				{/if}
				<!-- 위치 -->
				{#if popup.venue_name}
					<span class="text-gray-600 truncate max-w-[120px]">{popup.venue_name}</span>
				{/if}
				<!-- 방문 상태 -->
				<span
					class="ml-auto px-1.5 py-0.5 rounded {popup.is_visited
						? 'bg-green-100 text-green-700'
						: 'bg-gray-100 text-gray-500'}"
				>
					{popup.is_visited ? '방문' : '미방문'}
				</span>
			</div>
		</div>
	{/each}
</div>
