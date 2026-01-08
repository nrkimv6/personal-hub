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
		isAdmin?: boolean;
		isParticipated: (event: Event) => boolean;
		onEventClick: (event: Event) => void;
		onBookmarkToggle: (event: Event, e: MouseEvent) => void;
		onParticipateToggle: (event: Event, e: MouseEvent) => void;
	}

	let { events, isAdmin = false, isParticipated, onEventClick, onBookmarkToggle, onParticipateToggle }: Props =
		$props();

	let copiedEventId: number | null = $state(null);

	async function copyEventUrl(event: Event, e: MouseEvent) {
		e.stopPropagation();
		if (!event.event_url) return;

		try {
			await navigator.clipboard.writeText(event.event_url);
			copiedEventId = event.id;
			setTimeout(() => {
				copiedEventId = null;
			}, 2000);
		} catch (err) {
			console.error('Failed to copy URL:', err);
		}
	}
</script>

<div class="md:hidden space-y-3 mb-6">
	{#each events as event (event.id)}
		<div
			class="rounded-lg border p-3 cursor-pointer hover:shadow-card-hover transition-all {isParticipated(event)
				? 'bg-muted border-border opacity-60'
				: isEndingToday(event)
					? 'bg-warning-light border-warning'
					: isUnknownPeriod(event)
						? 'bg-warning-light border-warning-muted'
						: 'bg-card border-border'}"
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
							<span class="px-1.5 py-0.5 text-xs rounded bg-pink-light text-pink">IG</span>
						{/if}
						{#if event.purchase_required === 'no'}
							<span class="px-1.5 py-0.5 text-xs rounded bg-success-light text-success">무료</span>
						{:else if event.purchase_required === 'yes_all'}
							<span class="px-1.5 py-0.5 text-xs rounded bg-error-light text-error">구매</span>
						{/if}
					</div>
					<h3 class="font-medium text-foreground truncate" title={event.title}>{event.title}</h3>
					{#if event.organizer}
						<p class="text-sm text-primary truncate">{event.organizer}</p>
					{/if}
				</div>
				<!-- 북마크/복사 버튼 -->
				<div class="flex items-center gap-1" onclick={(e) => e.stopPropagation()}>
					{#if isAdmin && event.event_url}
						{@const urlCount = 1 + (event.additional_urls?.length || 0)}
						<button
							onclick={(e) => copyEventUrl(event, e)}
							class="p-1.5 rounded-lg transition-colors flex items-center gap-0.5 {copiedEventId === event.id
								? 'bg-success-light text-success'
								: 'bg-muted text-muted-foreground hover:bg-secondary'}"
							title={copiedEventId === event.id ? '복사됨!' : '메인 링크 복사'}
						>
							{#if copiedEventId === event.id}
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							{:else}
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
								</svg>
							{/if}
							{#if urlCount > 1}
								<span class="text-[10px] font-medium">+{urlCount - 1}</span>
							{/if}
						</button>
					{/if}
					<button
						onclick={(e) => onBookmarkToggle(event, e)}
						class="text-xl transition-colors {event.is_bookmarked
							? 'text-warning'
							: 'text-muted-foreground hover:text-warning'}"
					>
						{event.is_bookmarked ? '★' : '☆'}
					</button>
				</div>
			</div>
			<div class="flex items-center gap-2 text-xs text-muted-foreground">
				<div class="flex flex-wrap items-center gap-2 flex-1">
					<!-- 기간 -->
					{#if event.event_end}
						{#if isEndingToday(event)}
							<span class="font-bold text-warning bg-warning-light px-1.5 py-0.5 rounded"
								>오늘 마감!</span
							>
						{:else}
							<span>~ {formatDate(event.event_end)}</span>
						{/if}
					{:else}
						<span class="text-warning bg-warning-light px-1.5 py-0.5 rounded">기간 미정</span>
					{/if}
					<!-- 경품 -->
					{#if event.prizes && event.prizes.length > 0}
						<span class="text-warning-foreground bg-warning-light px-1.5 py-0.5 rounded truncate max-w-[100px]"
							>{event.prizes[0]}</span
						>
					{/if}
					<!-- 당첨자 수 -->
					{#if event.winner_count}
						<span class="text-purple">{event.winner_count}명</span>
					{/if}
				</div>
				<!-- 참여 체크박스 (큰 사이즈) -->
				<button
					onclick={(e) => onParticipateToggle(event, e)}
					class="flex items-center justify-center w-10 h-10 rounded-lg border-2 transition-all {isParticipated(
						event
					)
						? 'bg-success border-success text-success-foreground'
						: 'bg-card border-border text-muted-foreground hover:border-success'}"
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
