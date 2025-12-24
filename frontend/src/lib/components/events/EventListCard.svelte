<script lang="ts">
	/**
	 * 이벤트 모바일 카드 컴포넌트
	 *
	 * 모바일 환경에서 이벤트 목록을 카드 형식으로 표시
	 */
	import type { Event } from '$lib/types';
	import {
		formatDate,
		getEventStatusColor,
		getEventStatusLabel,
		isEndingToday,
		isUnknownPeriod
	} from '$lib/utils/eventUtils';

	interface Props {
		events: Event[];
		isParticipated: (event: Event) => boolean;
		onEventClick: (event: Event) => void;
		onBookmarkToggle: (event: Event, e: MouseEvent) => void;
		onParticipateToggle: (event: Event, e: MouseEvent) => void;
	}

	let { events, isParticipated, onEventClick, onBookmarkToggle, onParticipateToggle }: Props =
		$props();
</script>

<div class="md:hidden space-y-3 mb-6">
	{#each events as event (event.id)}
		<div
			class="rounded-lg border p-3 cursor-pointer hover:shadow-md transition-all {isParticipated(event)
				? 'bg-gray-100 border-gray-200 opacity-60'
				: isEndingToday(event)
					? 'bg-orange-50 border-orange-300'
					: isUnknownPeriod(event)
						? 'bg-amber-50 border-amber-200'
						: 'bg-white border-gray-200'}"
			onclick={() => onEventClick(event)}
			onkeydown={(e) => e.key === 'Enter' && onEventClick(event)}
			role="button"
			tabindex="0"
		>
			<div class="flex justify-between items-start gap-2 mb-2">
				<div class="flex-1 min-w-0">
					<div class="flex items-center gap-2 mb-1">
						<span class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(event.event_status)}">
							{getEventStatusLabel(event.event_status)}
						</span>
						{#if event.source_type === 'instagram'}
							<span class="px-1.5 py-0.5 text-xs rounded bg-pink-100 text-pink-600">IG</span>
						{/if}
						{#if event.purchase_required === 'no'}
							<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 text-green-600">무료</span>
						{:else if event.purchase_required === 'yes_all'}
							<span class="px-1.5 py-0.5 text-xs rounded bg-red-100 text-red-600">구매</span>
						{/if}
					</div>
					<h3 class="font-medium text-gray-900 truncate" title={event.title}>{event.title}</h3>
					{#if event.organizer}
						<p class="text-sm text-blue-600 truncate">{event.organizer}</p>
					{/if}
				</div>
				<!-- 북마크 버튼 -->
				<div class="flex items-center gap-1" onclick={(e) => e.stopPropagation()}>
					<button
						onclick={(e) => onBookmarkToggle(event, e)}
						class="text-xl transition-colors {event.is_bookmarked
							? 'text-yellow-500'
							: 'text-gray-300'}"
					>
						{event.is_bookmarked ? '★' : '☆'}
					</button>
				</div>
			</div>
			<div class="flex items-center gap-2 text-xs text-gray-500">
				<div class="flex flex-wrap items-center gap-2 flex-1">
					<!-- 기간 -->
					{#if event.event_end}
						{#if isEndingToday(event)}
							<span class="font-bold text-orange-600 bg-orange-100 px-1.5 py-0.5 rounded"
								>오늘 마감!</span
							>
						{:else}
							<span>~ {formatDate(event.event_end)}</span>
						{/if}
					{:else}
						<span class="text-amber-600 bg-amber-100 px-1.5 py-0.5 rounded">기간 미정</span>
					{/if}
					<!-- 경품 -->
					{#if event.prizes && event.prizes.length > 0}
						<span class="text-yellow-700 bg-yellow-50 px-1.5 py-0.5 rounded truncate max-w-[100px]"
							>{event.prizes[0]}</span
						>
					{/if}
					<!-- 당첨자 수 -->
					{#if event.winner_count}
						<span class="text-purple-600">{event.winner_count}명</span>
					{/if}
				</div>
				<!-- 참여 체크박스 (큰 사이즈) -->
				<button
					onclick={(e) => onParticipateToggle(event, e)}
					class="flex items-center justify-center w-10 h-10 rounded-lg border-2 transition-all {isParticipated(
						event
					)
						? 'bg-green-500 border-green-500 text-white'
						: 'bg-white border-gray-300 text-gray-400 hover:border-green-400'}"
					title={isParticipated(event) ? '참여 취소' : '참여 완료'}
				>
					{#if isParticipated(event)}
						<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="3"
								d="M5 13l4 4L19 7"
							/>
						</svg>
					{:else}
						<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M5 13l4 4L19 7"
							/>
						</svg>
					{/if}
				</button>
			</div>
		</div>
	{/each}
</div>
