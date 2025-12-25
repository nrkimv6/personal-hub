<script lang="ts">
	/**
	 * 팝업 데스크톱 테이블 컴포넌트
	 *
	 * 데스크톱 환경에서 팝업 목록을 테이블 형식으로 표시
	 * 팝업 전용 컬럼: 브랜드, 위치, 방문 상태
	 */
	import type { Popup } from '$lib/types';
	import {
		formatDate,
		getEventStatusColor,
		getEventStatusLabel,
		isPopupEndingToday,
		isPopupUnknownPeriod,
		truncate
	} from '$lib/utils/eventUtils';

	interface Props {
		popups: Popup[];
		onPopupClick: (popup: Popup) => void;
		onBookmarkToggle: (popup: Popup, e: MouseEvent) => void;
		onVisitedToggle: (popup: Popup, e: MouseEvent) => void;
	}

	let { popups, onPopupClick, onBookmarkToggle, onVisitedToggle }: Props = $props();

	async function openInstagramSource(popup: Popup, e: MouseEvent) {
		e.stopPropagation();

		if (popup.source_instagram_url) {
			window.open(popup.source_instagram_url, '_blank');
			return;
		}

		try {
			const res = await fetch(`/api/v1/popups/${popup.id}/instagram-source`);
			const data = await res.json();
			if (data.url) {
				window.open(data.url, '_blank');
			}
		} catch (err) {
			console.error('Failed to fetch Instagram source:', err);
		}
	}
</script>

<div class="hidden md:block bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
	<div class="overflow-x-auto">
		<table class="w-full">
			<thead class="bg-gray-50 border-b border-gray-200">
				<tr>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
						>상태</th
					>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
						>브랜드</th
					>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[180px]"
						>제목</th
					>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
						>기간</th
					>
					<th
						class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[150px]"
						>위치</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
						>출처</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
						>원본</th
					>
					<th
						class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
						>관리</th
					>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-200">
				{#each popups as popup (popup.id)}
					<tr
						class="cursor-pointer transition-colors {isPopupEndingToday(popup)
							? 'bg-orange-100 hover:bg-orange-200 font-semibold'
							: isPopupUnknownPeriod(popup)
								? 'bg-amber-50 hover:bg-amber-100'
								: 'hover:bg-gray-50'}"
						onclick={() => onPopupClick(popup)}
					>
						<!-- 상태 -->
						<td class="px-2 py-2">
							<span
								class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(popup.popup_status)}"
							>
								{getEventStatusLabel(popup.popup_status)}
							</span>
						</td>
						<!-- 브랜드/주최 -->
						<td class="px-2 py-2 max-w-[100px]">
							{#if popup.brand || popup.organizer}
								<span
									class="text-sm font-medium text-blue-600 truncate block"
									title={popup.brand || popup.organizer}
								>
									{popup.brand || popup.organizer}
								</span>
							{:else}
								<span class="text-xs text-gray-400">-</span>
							{/if}
						</td>
						<!-- 제목 -->
						<td class="px-2 py-2 max-w-[180px]">
							<span class="block truncate text-sm font-medium text-gray-900" title={popup.title}>
								{popup.title}
							</span>
							{#if popup.summary}
								<span
									class="block truncate text-xs text-gray-500 line-clamp-2"
									title={popup.summary}
								>
									{truncate(popup.summary, 40)}
								</span>
							{/if}
						</td>
						<!-- 기간 -->
						<td class="px-2 py-2 text-sm text-gray-600 whitespace-nowrap">
							{#if popup.end_date}
								<div class="flex flex-col gap-0.5">
									{#if popup.start_date}
										<span class="text-xs text-gray-500">{formatDate(popup.start_date)}</span>
									{/if}
									{#if isPopupEndingToday(popup)}
										<span class="text-xs font-bold text-orange-600 bg-orange-50 px-1 rounded"
											>오늘 마감!</span
										>
									{:else}
										<span class="text-xs text-gray-500">~ {formatDate(popup.end_date)}</span>
									{/if}
								</div>
							{:else if popup.start_date}
								<div class="flex flex-col gap-0.5">
									<span class="text-xs text-gray-500">{formatDate(popup.start_date)} ~</span>
									<span class="text-xs text-amber-600 bg-amber-50 px-1 rounded">기간 미정</span>
								</div>
							{:else}
								<span class="text-xs text-amber-600 bg-amber-50 px-1 rounded">기간 미정</span>
							{/if}
						</td>
						<!-- 위치 -->
						<td class="px-2 py-2 max-w-[150px]">
							{#if popup.venue_name}
								<div class="flex flex-col">
									<span class="text-xs font-medium text-gray-700 truncate" title={popup.venue_name}>
										{popup.venue_name}
									</span>
									{#if popup.address}
										<span class="text-xs text-gray-500 truncate" title={popup.address}>
											{truncate(popup.address, 20)}
										</span>
									{/if}
								</div>
							{:else}
								<span class="text-xs text-gray-400">-</span>
							{/if}
						</td>
						<!-- 출처 -->
						<td class="px-2 py-2 text-center">
							<span
								class="px-1.5 py-0.5 text-xs rounded {popup.source_type === 'instagram'
									? 'bg-pink-100 text-pink-600'
									: 'bg-gray-100 text-gray-600'}"
							>
								{popup.source_type === 'instagram'
									? 'IG'
									: popup.source_type === 'manual'
										? '수동'
										: popup.source_type}
							</span>
						</td>
						<!-- 원본 링크 -->
						<td class="px-2 py-2 text-center" onclick={(e) => e.stopPropagation()}>
							<div class="flex gap-1 justify-center">
								{#if popup.official_url}
									<a
										href={popup.official_url}
										target="_blank"
										rel="noopener noreferrer"
										class="text-xs text-blue-600 hover:text-blue-800 hover:underline"
										title="공식 사이트"
									>
										공식
									</a>
								{/if}
								{#if popup.source_type === 'instagram' && (popup.source_instagram_url || popup.source_instagram_post_id)}
									<button
										onclick={(e) => openInstagramSource(popup, e)}
										class="text-xs text-pink-600 hover:text-pink-800 hover:underline font-medium"
										title="Instagram 원본"
									>
										IG
									</button>
								{/if}
								{#if !popup.official_url && !(popup.source_type === 'instagram' && (popup.source_instagram_url || popup.source_instagram_post_id))}
									<span class="text-xs text-gray-400">-</span>
								{/if}
							</div>
						</td>
						<!-- 관리 (북마크/방문) -->
						<td class="px-2 py-2" onclick={(e) => e.stopPropagation()}>
							<div class="flex items-center gap-1 justify-center">
								<button
									onclick={(e) => onBookmarkToggle(popup, e)}
									class="text-lg transition-colors {popup.is_bookmarked
										? 'text-yellow-500'
										: 'text-gray-300 hover:text-yellow-400'}"
									title={popup.is_bookmarked ? '북마크 해제' : '북마크'}
								>
									{popup.is_bookmarked ? '★' : '☆'}
								</button>
								<button
									onclick={(e) => onVisitedToggle(popup, e)}
									class="px-1.5 py-0.5 text-xs rounded transition-colors {popup.is_visited
										? 'bg-green-100 text-green-700'
										: 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
									title={popup.is_visited ? '방문 취소' : '방문 완료'}
								>
									{popup.is_visited ? '방문' : '미방문'}
								</button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
