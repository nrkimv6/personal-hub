<script lang="ts">
	/**
	 * 이벤트 데스크톱 테이블 컴포넌트
	 *
	 * 데스크톱 환경에서 이벤트 목록을 테이블 형식으로 표시
	 * 이벤트 전용 컬럼: 발표일, 경품, 당첨자, 조건, 수집일
	 */
	import type { Event } from '$lib/types';
	import { fetchWithTimeout } from '$lib/api/client';
	import {
		formatDate,
		getEventStatusColor,
		getEventStatusLabel,
		isEndingToday,
		isUnknownPeriod,
		truncate
	} from '$lib/utils/eventUtils';

	interface Props {
		events: Event[];
		sortBy: string;
		sortOrder: string;
		showTypeColumn?: boolean; // 'all' 탭에서만 true
		isAdmin?: boolean;
		isParticipated: (event: Event) => boolean;
		onSort: (column: string) => void;
		onEventClick: (event: Event) => void;
		onBookmarkToggle: (event: Event, e: MouseEvent) => void;
		onParticipateToggle: (event: Event, e: MouseEvent) => void;
	}

	let {
		events,
		sortBy,
		sortOrder,
		showTypeColumn = false,
		isAdmin = false,
		isParticipated,
		onSort,
		onEventClick,
		onBookmarkToggle,
		onParticipateToggle
	}: Props = $props();

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

	async function openInstagramSource(event: Event, e: MouseEvent) {
		e.stopPropagation();

		// 이미 URL이 있으면 바로 열기
		if (event.source_instagram_url) {
			window.open(event.source_instagram_url, '_blank');
			return;
		}

		// API로 가져오기
		try {
			const res = await fetchWithTimeout(`/api/v1/events/${event.id}/instagram-source`);
			const data = await res.json();
			if (data.url) {
				window.open(data.url, '_blank');
			}
		} catch (err) {
			console.error('Failed to fetch Instagram source:', err);
		}
	}

	function getSortIcon(column: string): string {
		if (sortBy !== column) return '↕';
		return sortOrder === 'asc' ? '↑' : '↓';
	}
</script>

<div class="hidden md:block bg-card rounded-lg border border-border overflow-hidden mb-6">
	<div class="overflow-x-auto">
		<table class="w-full">
			<thead class="bg-muted border-b border-border">
				<tr>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap"
						>상태</th
					>
					{#if showTypeColumn}
						<th
							class="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap"
							>유형</th
						>
					{/if}
					<th
						class="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap cursor-pointer hover:bg-secondary select-none"
						onclick={() => onSort('organizer')}
					>
						주최 <span class="text-muted-foreground/50">{getSortIcon('organizer')}</span>
					</th>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap max-w-[180px] cursor-pointer hover:bg-secondary select-none"
						onclick={() => onSort('title')}
					>
						제목 <span class="text-muted-foreground/50">{getSortIcon('title')}</span>
					</th>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap cursor-pointer hover:bg-secondary select-none"
						onclick={() => onSort('event_end')}
					>
						기간 <span class="text-muted-foreground/50">{getSortIcon('event_end')}</span>
					</th>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap cursor-pointer hover:bg-secondary select-none"
						onclick={() => onSort('announcement_date')}
					>
						발표일 <span class="text-muted-foreground/50">{getSortIcon('announcement_date')}</span>
					</th>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap max-w-[120px]"
						>경품</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase whitespace-nowrap"
						>당첨자</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase whitespace-nowrap"
						>조건</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase whitespace-nowrap cursor-pointer hover:bg-secondary select-none"
						onclick={() => onSort('created_at')}
					>
						수집일 <span class="text-muted-foreground/50">{getSortIcon('created_at')}</span>
					</th>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase whitespace-nowrap"
						>출처</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase whitespace-nowrap"
						>원본</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-muted-foreground uppercase whitespace-nowrap"
						>관리</th
					>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each events as event (event.id)}
					<tr
						class="cursor-pointer transition-all {isParticipated(event)
							? 'bg-muted opacity-50 hover:opacity-70'
							: isEndingToday(event)
								? 'bg-warning-light hover:bg-warning-light/80 font-semibold'
								: isUnknownPeriod(event)
									? 'bg-warning-light/50 hover:bg-warning-light/70'
									: 'hover:bg-muted'}"
						onclick={() => onEventClick(event)}
					>
						<!-- 상태 -->
						<td class="px-2 py-2">
							<span
								class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(event.event_status)}"
							>
								{getEventStatusLabel(event.event_status)}
							</span>
						</td>
						<!-- 유형 (all 탭만) -->
						{#if showTypeColumn}
							<td class="px-2 py-2">
								<span
									class="px-2 py-0.5 text-xs rounded {event.event_type === 'popup'
										? 'bg-pink-light text-pink'
										: event.event_type === 'event'
											? 'bg-purple-light text-purple'
											: 'bg-muted text-muted-foreground'}"
								>
									{event.event_type === 'popup'
										? '팝업'
										: event.event_type === 'event'
											? '이벤트'
											: event.event_type}
								</span>
							</td>
						{/if}
						<!-- 주최 -->
						<td class="px-2 py-2 max-w-[100px]">
							{#if event.organizer}
								<span
									class="text-sm font-medium text-primary truncate block"
									title={event.organizer}
								>
									{event.organizer}
								</span>
							{:else}
								<span class="text-xs text-muted-foreground">-</span>
							{/if}
						</td>
						<!-- 제목 -->
						<td class="px-2 py-2 max-w-[180px]">
							<span class="block truncate text-sm font-medium text-foreground" title={event.title}>
								{event.title}
							</span>
							{#if event.summary}
								<span
									class="block truncate text-xs text-muted-foreground line-clamp-2"
									title={event.summary}
								>
									{truncate(event.summary, 40)}
								</span>
							{/if}
						</td>
						<!-- 기간 -->
						<td class="px-2 py-2 text-sm text-muted-foreground whitespace-nowrap">
							{#if event.event_end}
								<div class="flex flex-col gap-0.5">
									{#if event.event_start}
										<span class="text-xs text-muted-foreground">{formatDate(event.event_start)}</span>
									{/if}
									{#if isEndingToday(event)}
										<span class="text-xs font-bold text-warning bg-warning-light px-1 rounded"
											>오늘 마감!</span
										>
									{:else}
										<span class="text-xs text-muted-foreground">~ {formatDate(event.event_end)}</span>
									{/if}
								</div>
							{:else if event.event_start}
								<div class="flex flex-col gap-0.5">
									<span class="text-xs text-muted-foreground">{formatDate(event.event_start)} ~</span>
									<span class="text-xs text-warning bg-warning-light px-1 rounded">기간 미정</span>
								</div>
							{:else}
								<span class="text-xs text-warning bg-warning-light px-1 rounded">기간 미정</span>
							{/if}
						</td>
						<!-- 발표일 -->
						<td class="px-2 py-2 text-xs text-muted-foreground whitespace-nowrap">
							{#if event.announcement_date}
								<span class="text-foreground">{formatDate(event.announcement_date)}</span>
							{:else}
								<span class="text-muted-foreground">-</span>
							{/if}
						</td>
						<!-- 경품 -->
						<td class="px-2 py-2 max-w-[120px]">
							{#if event.prizes && event.prizes.length > 0}
								<div class="flex flex-wrap gap-0.5">
									{#each event.prizes.slice(0, 2) as prize}
										<span
											class="text-xs bg-warning-light text-warning-foreground px-1 rounded truncate max-w-[100px]"
											title={prize}
										>
											{truncate(prize, 12)}
										</span>
									{/each}
									{#if event.prizes.length > 2}
										<span class="text-xs text-muted-foreground">+{event.prizes.length - 2}개</span>
									{/if}
								</div>
							{:else}
								<span class="text-xs text-muted-foreground">-</span>
							{/if}
						</td>
						<!-- 당첨자 -->
						<td class="px-2 py-2 text-center">
							{#if event.winner_count}
								<span class="text-sm font-medium text-purple">{event.winner_count}명</span>
							{:else}
								<span class="text-xs text-muted-foreground">-</span>
							{/if}
						</td>
						<!-- 조건 -->
						<td class="px-2 py-2 text-center">
							{#if event.purchase_required === 'yes_all'}
								<span class="text-xs bg-error-light text-error px-1.5 py-0.5 rounded">구매필수</span>
							{:else if event.purchase_required === 'yes_partial'}
								<span class="text-xs bg-warning-light text-warning px-1.5 py-0.5 rounded"
									>부분구매</span
								>
							{:else if event.purchase_required === 'no'}
								<span class="text-xs bg-success-light text-success px-1.5 py-0.5 rounded">무료</span>
							{:else}
								<span class="text-xs text-muted-foreground">-</span>
							{/if}
						</td>
						<!-- 수집일 -->
						<td class="px-2 py-2 text-center text-xs text-muted-foreground whitespace-nowrap">
							{formatDate(event.created_at)}
						</td>
						<!-- 출처 -->
						<td class="px-2 py-2 text-center">
							<span
								class="px-1.5 py-0.5 text-xs rounded {event.source_type === 'instagram'
									? 'bg-pink-light text-pink'
									: 'bg-muted text-muted-foreground'}"
							>
								{event.source_type === 'instagram'
									? 'IG'
									: event.source_type === 'manual'
										? '수동'
										: event.source_type}
							</span>
						</td>
						<!-- 원본 링크 -->
						<td class="px-2 py-2 text-center" onclick={(e) => e.stopPropagation()}>
							<div class="flex gap-1 justify-center items-center">
								{#if event.event_url}
									{@const urlCount = 1 + (event.additional_urls?.length || 0)}
									<a
										href={event.event_url}
										target="_blank"
										rel="noopener noreferrer"
										class="text-xs text-primary hover:text-primary-hover hover:underline"
										title="이벤트 참여"
									>
										참여
									</a>
									{#if urlCount > 1}
										<span class="text-[10px] text-primary-muted font-medium" title="{urlCount}개 링크">+{urlCount - 1}</span>
									{/if}
									{#if isAdmin}
										<button
											onclick={(e) => copyEventUrl(event, e)}
											class="p-0.5 rounded hover:bg-muted transition-colors"
											title={copiedEventId === event.id ? '복사됨!' : '메인 링크 복사'}
										>
											{#if copiedEventId === event.id}
												<svg class="w-3.5 h-3.5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
												</svg>
											{:else}
												<svg class="w-3.5 h-3.5 text-muted-foreground hover:text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
												</svg>
											{/if}
										</button>
									{/if}
								{/if}
								{#if event.source_type === 'instagram' && (event.source_instagram_url || event.source_instagram_post_id)}
									<button
										onclick={(e) => openInstagramSource(event, e)}
										class="text-xs text-pink hover:text-pink/80 hover:underline font-medium"
										title="Instagram 원본"
									>
										IG
									</button>
								{/if}
								{#if !event.event_url && !(event.source_type === 'instagram' && (event.source_instagram_url || event.source_instagram_post_id))}
									<span class="text-xs text-muted-foreground">-</span>
								{/if}
							</div>
						</td>
						<!-- 관리 (북마크/참여) -->
						<td class="px-2 py-2" onclick={(e) => e.stopPropagation()}>
							<div class="flex items-center gap-1 justify-center">
								<button
									onclick={(e) => onBookmarkToggle(event, e)}
									class="text-lg transition-colors {event.is_bookmarked
										? 'text-warning'
										: 'text-muted-foreground hover:text-warning'}"
									title={event.is_bookmarked ? '북마크 해제' : '북마크'}
								>
									{event.is_bookmarked ? '★' : '☆'}
								</button>
								<button
									onclick={(e) => onParticipateToggle(event, e)}
									class="px-1.5 py-0.5 text-xs rounded transition-colors {isParticipated(event)
										? 'bg-success-light text-success'
										: 'bg-muted text-muted-foreground hover:bg-secondary'}"
									title={isParticipated(event) ? '참여 취소' : '참여 완료'}
								>
									{isParticipated(event) ? '참여' : '미참여'}
								</button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
