<script lang="ts">
	/**
	 * 검색결과 데스크톱 테이블 컴포넌트
	 */
	import type { SearchResultListItem } from '$lib/types';
	import {
		getRankChangeStyle,
		formatRankChange,
		truncateSnippet,
		formatRelativeDate,
		formatDate,
		extractDomain,
		getRowClasses
	} from '$lib/utils/searchResultUtils';

	interface Props {
		results: SearchResultListItem[];
		sortBy: string;
		sortOrder: string;
		onResultClick: (result: SearchResultListItem) => void;
		onBookmarkToggle: (result: SearchResultListItem, e: MouseEvent) => void;
		onReadToggle: (result: SearchResultListItem, e: MouseEvent) => void;
		onSort: (column: string) => void;
	}

	let { results, sortBy, sortOrder, onResultClick, onBookmarkToggle, onReadToggle, onSort }: Props = $props();

	function getSortIcon(column: string): string {
		if (sortBy !== column) return '↕';
		return sortOrder === 'asc' ? '↑' : '↓';
	}

	function openUrl(url: string, e: MouseEvent) {
		e.stopPropagation();
		window.open(url, '_blank', 'noopener,noreferrer');
	}
</script>

<div class="hidden md:block overflow-x-auto">
	<table class="w-full text-sm">
		<thead class="bg-muted/50 sticky top-0">
			<tr class="border-b border-border">
				<th class="px-3 py-2 text-left font-medium text-muted-foreground w-16">상태</th>
				<th
					class="px-3 py-2 text-left font-medium text-muted-foreground cursor-pointer hover:bg-muted w-16"
					onclick={() => onSort('rank')}
				>
					순위 {getSortIcon('rank')}
				</th>
				<th
					class="px-3 py-2 text-left font-medium text-muted-foreground cursor-pointer hover:bg-muted w-32"
					onclick={() => onSort('query')}
				>
					검색어 {getSortIcon('query')}
				</th>
				<th class="px-3 py-2 text-left font-medium text-muted-foreground min-w-[200px]">제목</th>
				<th class="px-3 py-2 text-left font-medium text-muted-foreground w-40">URL</th>
				<th class="px-3 py-2 text-left font-medium text-muted-foreground w-48">스니펫</th>
				<th
					class="px-3 py-2 text-left font-medium text-muted-foreground cursor-pointer hover:bg-muted w-24"
					onclick={() => onSort('publish_date')}
				>
					게시일 {getSortIcon('publish_date')}
				</th>
				<th
					class="px-3 py-2 text-left font-medium text-muted-foreground cursor-pointer hover:bg-muted w-24"
					onclick={() => onSort('created_at')}
				>
					수집일 {getSortIcon('created_at')}
				</th>
				<th class="px-3 py-2 text-left font-medium text-muted-foreground w-32">출처</th>
				<th class="px-3 py-2 text-center font-medium text-muted-foreground w-20">관리</th>
			</tr>
		</thead>
		<tbody>
			{#each results as result (result.id)}
				{@const rankStyle = getRankChangeStyle(result)}
				<tr
					class="border-b border-border hover:bg-muted/30 cursor-pointer transition-colors {getRowClasses(result)}"
					onclick={() => onResultClick(result)}
				>
					<!-- 상태 -->
					<td class="px-3 py-2">
						<span class="px-2 py-0.5 text-xs rounded-full font-medium whitespace-nowrap {rankStyle.color} {rankStyle.bg}">
							{formatRankChange(result)}
						</span>
					</td>

					<!-- 순위 -->
					<td class="px-3 py-2 font-bold text-gray-700">
						#{result.rank}
						{#if result.prev_rank !== null && result.prev_rank !== undefined}
							<span class="text-xs text-muted-foreground ml-1">(이전 #{result.prev_rank})</span>
						{/if}
					</td>

					<!-- 검색어 -->
					<td class="px-3 py-2">
						<span class="text-primary font-medium truncate block max-w-[120px]" title={result.query}>
							{result.query}
						</span>
					</td>

					<!-- 제목 -->
					<td class="px-3 py-2">
						<span class="truncate block max-w-[250px] text-foreground" title={result.title}>
							{result.title}
						</span>
					</td>

					<!-- URL -->
					<td class="px-3 py-2">
						<button
							class="text-blue-600 hover:underline truncate block max-w-[150px] text-left"
							title={result.url}
							onclick={(e) => openUrl(result.url, e)}
						>
							{result.display_url || extractDomain(result.url)}
						</button>
					</td>

					<!-- 스니펫 -->
					<td class="px-3 py-2 text-muted-foreground">
						<span class="truncate block max-w-[180px]" title={result.snippet || ''}>
							{truncateSnippet(result.snippet, 50)}
						</span>
					</td>

					<!-- 게시일 -->
					<td class="px-3 py-2 text-muted-foreground whitespace-nowrap">
						{result.publish_date || '-'}
					</td>

					<!-- 수집일 -->
					<td class="px-3 py-2 text-muted-foreground whitespace-nowrap">
						{formatRelativeDate(result.created_at)}
					</td>

					<!-- 출처 -->
					<td class="px-3 py-2">
						<span class="truncate block max-w-[120px] text-muted-foreground" title={result.saved_search_name || result.schedule_name || ''}>
							{result.saved_search_name || result.schedule_name || '-'}
						</span>
					</td>

					<!-- 관리 -->
					<td class="px-3 py-2">
						<div class="flex items-center justify-center gap-1" onclick={(e) => e.stopPropagation()}>
							<button
								onclick={(e) => onBookmarkToggle(result, e)}
								class="p-1 rounded transition-colors {result.is_bookmarked
									? 'text-yellow-500 hover:text-yellow-600'
									: 'text-gray-400 hover:text-yellow-500'}"
								title={result.is_bookmarked ? '북마크 해제' : '북마크'}
							>
								{result.is_bookmarked ? '★' : '☆'}
							</button>
							<button
								onclick={(e) => onReadToggle(result, e)}
								class="p-1 rounded transition-colors {result.is_read
									? 'text-green-500 hover:text-green-600'
									: 'text-gray-400 hover:text-green-500'}"
								title={result.is_read ? '읽지 않음으로 표시' : '읽음으로 표시'}
							>
								{result.is_read ? '읽음' : '○'}
							</button>
						</div>
					</td>
				</tr>
			{/each}

			{#if results.length === 0}
				<tr>
					<td colspan="10" class="px-3 py-8 text-center text-muted-foreground">
						검색결과가 없습니다.
					</td>
				</tr>
			{/if}
		</tbody>
	</table>
</div>
