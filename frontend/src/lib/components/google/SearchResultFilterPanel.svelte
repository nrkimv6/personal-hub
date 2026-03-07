<script lang="ts">
	/**
	 * 검색결과 필터 패널 컴포넌트
	 */
	import {
		RESULT_FILTER_TABS,
		RESULT_SORT_OPTIONS,
		READ_FILTER_OPTIONS,
		PAGE_SIZE_OPTIONS,
		type ResultFilterTabValue
	} from '$lib/constants/searchResultConstants';

	interface Props {
		activeTab: ResultFilterTabValue;
		query: string;
		search: string;
		dateFrom: string;
		dateTo: string;
		isRead: string;
		sortBy: string;
		sortOrder: string;
		pageSize: number;
		onTabChange: (tab: ResultFilterTabValue) => void;
		onQueryChange: (value: string) => void;
		onSearchChange: (value: string) => void;
		onDateFromChange: (value: string) => void;
		onDateToChange: (value: string) => void;
		onReadChange: (value: string) => void;
		onSortByChange: (value: string) => void;
		onSortOrderChange: (value: string) => void;
		onPageSizeChange: (value: number) => void;
		onReset: () => void;
	}

	let {
		activeTab,
		query,
		search,
		dateFrom,
		dateTo,
		isRead,
		sortBy,
		sortOrder,
		pageSize,
		onTabChange,
		onQueryChange,
		onSearchChange,
		onDateFromChange,
		onDateToChange,
		onReadChange,
		onSortByChange,
		onSortOrderChange,
		onPageSizeChange,
		onReset
	}: Props = $props();

	let showAdvanced = $state(false);
</script>

<div class="bg-card border border-border rounded-lg p-4 mb-4">
	<!-- 빠른 필터 탭 -->
	<div class="flex flex-wrap gap-2 mb-4">
		{#each RESULT_FILTER_TABS as tab}
			<button
				class="px-3 py-1.5 rounded-full text-sm font-medium transition-colors {activeTab === tab.value
					? 'bg-primary text-primary-foreground'
					: 'bg-muted text-muted-foreground hover:bg-secondary'}"
				onclick={() => onTabChange(tab.value)}
			>
				{tab.label}
			</button>
		{/each}
	</div>

	<!-- 기본 필터 -->
	<div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
		<!-- 검색어 필터 -->
		<div>
			<label class="block text-xs text-muted-foreground mb-1">검색어</label>
			<input
				type="text"
				value={query}
				oninput={(e) => onQueryChange(e.currentTarget.value)}
				placeholder="검색 키워드..."
				class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
			/>
		</div>

		<!-- 텍스트 검색 -->
		<div>
			<label class="block text-xs text-muted-foreground mb-1">제목/URL/스니펫</label>
			<input
				type="text"
				value={search}
				oninput={(e) => onSearchChange(e.currentTarget.value)}
				placeholder="검색..."
				class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
			/>
		</div>

		<!-- 정렬 -->
		<div>
			<label class="block text-xs text-muted-foreground mb-1">정렬</label>
			<div class="flex gap-1">
				<select
					value={sortBy}
					onchange={(e) => onSortByChange(e.currentTarget.value)}
					class="flex-1 px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
				>
					{#each RESULT_SORT_OPTIONS as option}
						<option value={option.value}>{option.label}</option>
					{/each}
				</select>
				<button
					onclick={() => onSortOrderChange(sortOrder === 'asc' ? 'desc' : 'asc')}
					class="px-3 py-2 border border-border rounded-lg bg-background hover:bg-muted transition-colors"
					title={sortOrder === 'asc' ? '오름차순' : '내림차순'}
				>
					{sortOrder === 'asc' ? '↑' : '↓'}
				</button>
			</div>
		</div>

		<!-- 페이지 크기 -->
		<div>
			<label class="block text-xs text-muted-foreground mb-1">표시 개수</label>
			<select
				value={pageSize}
				onchange={(e) => onPageSizeChange(Number(e.currentTarget.value))}
				class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
			>
				{#each PAGE_SIZE_OPTIONS as option}
					<option value={option.value}>{option.label}</option>
				{/each}
			</select>
		</div>
	</div>

	<!-- 상세 필터 토글 -->
	<button
		class="text-sm text-primary hover:underline mb-3"
		onclick={() => (showAdvanced = !showAdvanced)}
	>
		{showAdvanced ? '▲ 상세 필터 숨기기' : '▼ 상세 필터 보기'}
	</button>

	<!-- 상세 필터 -->
	{#if showAdvanced}
		<div class="grid grid-cols-1 md:grid-cols-4 gap-3 pt-3 border-t border-border">
			<!-- 기간 필터 -->
			<div>
				<label class="block text-xs text-muted-foreground mb-1">수집 시작일</label>
				<input
					type="date"
					value={dateFrom}
					oninput={(e) => onDateFromChange(e.currentTarget.value)}
					class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
				/>
			</div>
			<div>
				<label class="block text-xs text-muted-foreground mb-1">수집 종료일</label>
				<input
					type="date"
					value={dateTo}
					oninput={(e) => onDateToChange(e.currentTarget.value)}
					class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
				/>
			</div>

			<!-- 읽음 필터 -->
			<div>
				<label class="block text-xs text-muted-foreground mb-1">읽음 상태</label>
				<select
					value={isRead}
					onchange={(e) => onReadChange(e.currentTarget.value)}
					class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary"
				>
					{#each READ_FILTER_OPTIONS as option}
						<option value={option.value}>{option.label}</option>
					{/each}
				</select>
			</div>

			<!-- 초기화 버튼 -->
			<div class="flex items-end">
				<button
					onclick={onReset}
					class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-muted text-muted-foreground hover:bg-secondary transition-colors"
				>
					필터 초기화
				</button>
			</div>
		</div>
	{/if}
</div>
