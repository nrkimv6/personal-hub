<script lang="ts">
	/**
	 * 검색결과 모바일 카드 컴포넌트
	 */
	import type { SearchResultListItem } from '$lib/types';
	import {
		getRankChangeStyle,
		formatRankChange,
		truncateSnippet,
		formatRelativeDate,
		extractDomain,
		getRowClasses
	} from '$lib/utils/searchResultUtils';

	interface Props {
		results: SearchResultListItem[];
		onResultClick: (result: SearchResultListItem) => void;
		onBookmarkToggle: (result: SearchResultListItem, e: MouseEvent) => void;
		onReadToggle: (result: SearchResultListItem, e: MouseEvent) => void;
	}

	let { results, onResultClick, onBookmarkToggle, onReadToggle }: Props = $props();
</script>

<div class="md:hidden space-y-3 mb-6">
	{#each results as result (result.id)}
		{@const rankStyle = getRankChangeStyle(result)}
		<div
			class="rounded-lg border p-3 cursor-pointer hover:shadow-card-hover transition-all bg-card border-border {getRowClasses(result)}"
			onclick={() => onResultClick(result)}
			onkeydown={(e) => e.key === 'Enter' && onResultClick(result)}
			role="button"
			tabindex="0"
		>
			<!-- 상단: 배지 + 순위 + 관리 버튼 -->
			<div class="flex justify-between items-start gap-2 mb-2">
				<div class="flex items-center gap-2">
					<!-- 신규/순위변화 배지 -->
					<span class="px-2 py-0.5 text-xs rounded-full font-medium {rankStyle.color} {rankStyle.bg}">
						{formatRankChange(result)}
					</span>
					<!-- 순위 -->
					<span class="text-sm font-bold text-gray-700">#{result.rank}</span>
				</div>
				<!-- 북마크/읽음 버튼 -->
				<div role="presentation" class="flex items-center gap-1" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
					<button
						onclick={(e) => onBookmarkToggle(result, e)}
						class="p-1.5 rounded-lg transition-colors {result.is_bookmarked
							? 'bg-yellow-100 text-yellow-600'
							: 'bg-muted text-muted-foreground hover:bg-secondary'}"
						title={result.is_bookmarked ? '북마크 해제' : '북마크'}
					>
						{result.is_bookmarked ? '★' : '☆'}
					</button>
					<button
						onclick={(e) => onReadToggle(result, e)}
						class="p-1.5 rounded-lg transition-colors {result.is_read
							? 'bg-green-100 text-green-600'
							: 'bg-muted text-muted-foreground hover:bg-secondary'}"
						title={result.is_read ? '읽지 않음으로 표시' : '읽음으로 표시'}
					>
						{result.is_read ? '읽음' : '○'}
					</button>
				</div>
			</div>

			<!-- 검색어 -->
			<div class="text-xs text-muted-foreground mb-1">
				검색어: <span class="font-medium text-primary">{result.query}</span>
			</div>

			<!-- 제목 -->
			<h3 class="font-medium text-foreground line-clamp-2 mb-1" title={result.title}>
				{result.title}
			</h3>

			<!-- URL -->
			<p class="text-xs text-blue-600 truncate mb-2">
				{result.display_url || extractDomain(result.url)}
			</p>

			<!-- 스니펫 -->
			{#if result.snippet}
				<p class="text-sm text-muted-foreground line-clamp-2 mb-2">
					{truncateSnippet(result.snippet, 120)}
				</p>
			{/if}

			<!-- 하단: 날짜 + 출처 -->
			<div class="flex justify-between items-center text-xs text-muted-foreground border-t border-border pt-2 mt-2">
				<span>{formatRelativeDate(result.created_at)}</span>
				{#if result.saved_search_name || result.schedule_name}
					<span class="truncate max-w-[50%]">
						{result.saved_search_name || result.schedule_name}
					</span>
				{/if}
			</div>
		</div>
	{/each}

	{#if results.length === 0}
		<div class="text-center py-8 text-muted-foreground">
			검색결과가 없습니다.
		</div>
	{/if}
</div>
