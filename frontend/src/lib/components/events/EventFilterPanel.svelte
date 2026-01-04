<script lang="ts">
	/**
	 * 이벤트/팝업 필터 패널 컴포넌트
	 *
	 * 개선된 버전:
	 * - 기간미정 3단계 필터 (제외/포함/만)
	 * - 상태/마감일 필터 독립 동작
	 * - 정렬 옵션 (카드 뷰용)
	 * - 빠른 필터 프리셋
	 * - 현재 필터 상태 명시적 표시
	 * - URL/출처 고급 필터
	 */
	import {
		EVENT_STATUS_OPTIONS,
		UNKNOWN_PERIOD_OPTIONS,
		SORT_OPTIONS,
		QUICK_FILTER_PRESETS,
		URL_TYPE_OPTIONS,
		SOURCE_TYPE_OPTIONS
	} from '$lib/constants/eventConstants';

	interface Props {
		filterEventStatus: string | null;
		unknownPeriodFilter: string;
		showFilters: boolean;
		filterDeadlineDate: string | null;
		deadlineCounts: Record<string, number>;
		filterSearch: string;
		sortBy: string;
		sortOrder: string;
		// 고급 필터
		filterUrlType?: string | null;
		filterSourceType?: string | null;
		// 콜백
		onStatusFilterChange: (status: string | null) => void;
		onUnknownPeriodFilterChange: (filter: string) => void;
		onShowFiltersChange: (show: boolean) => void;
		onDeadlineDateChange: (date: string | null) => void;
		onSearchChange: (search: string) => void;
		onSearch: () => void;
		onSortChange: (sortBy: string, sortOrder: string) => void;
		onQuickFilter?: (preset: typeof QUICK_FILTER_PRESETS[number]) => void;
		onUrlTypeChange?: (urlType: string | null) => void;
		onSourceTypeChange?: (sourceType: string | null) => void;
	}

	let {
		filterEventStatus,
		unknownPeriodFilter = 'include',
		showFilters,
		filterDeadlineDate = null,
		deadlineCounts = {},
		filterSearch = '',
		sortBy = 'event_end',
		sortOrder = 'asc',
		filterUrlType = null,
		filterSourceType = null,
		onStatusFilterChange,
		onUnknownPeriodFilterChange,
		onShowFiltersChange,
		onDeadlineDateChange,
		onSearchChange,
		onSearch,
		onSortChange,
		onQuickFilter,
		onUrlTypeChange,
		onSourceTypeChange
	}: Props = $props();

	// 고급 필터 토글
	let showAdvancedFilters = $state(false);

	function handleSearchKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			onSearch();
		}
	}

	function clearSearch() {
		onSearchChange('');
		onSearch();
	}

	function setEventStatusFilter(status: string) {
		// 빈 문자열('')은 null로 처리 (전체)
		const newStatus = status === '' ? null : (filterEventStatus === status ? null : status);
		onStatusFilterChange(newStatus);
	}

	function setDeadlineDateFilter(dateStr: string) {
		onDeadlineDateChange(filterDeadlineDate === dateStr ? null : dateStr);
	}

	function setUnknownPeriodFilter(filter: string) {
		onUnknownPeriodFilterChange(filter);
	}

	function handleSortChange(newSortBy: string) {
		if (sortBy === newSortBy) {
			// 같은 정렬 기준 클릭 시 순서 토글
			onSortChange(newSortBy, sortOrder === 'asc' ? 'desc' : 'asc');
		} else {
			// 다른 정렬 기준 선택 시 기본 순서 적용
			const defaultOrder = ['created_at', 'event_end', 'event_start', 'announcement_date'].includes(newSortBy)
				? 'desc'
				: 'asc';
			onSortChange(newSortBy, defaultOrder);
		}
	}

	function applyQuickFilter(preset: typeof QUICK_FILTER_PRESETS[number]) {
		if (onQuickFilter) {
			onQuickFilter(preset);
		}
	}

	// 오늘부터 6일간 날짜 배열 생성
	function getDeadlineDates(): { dateStr: string; label: string; dayLabel: string }[] {
		const dates: { dateStr: string; label: string; dayLabel: string }[] = [];
		const today = new Date();
		const dayNames = ['일', '월', '화', '수', '목', '금', '토'];

		for (let i = 0; i < 6; i++) {
			const d = new Date(today);
			d.setDate(today.getDate() + i);
			const year = d.getFullYear();
			const month = d.getMonth() + 1;
			const day = d.getDate();
			const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
			const dayOfWeek = dayNames[d.getDay()];

			let dayLabel: string;
			if (i === 0) dayLabel = '오늘';
			else if (i === 1) dayLabel = '내일';
			else dayLabel = dayOfWeek;

			dates.push({
				dateStr,
				label: `${month}/${day}`,
				dayLabel
			});
		}
		return dates;
	}

	const deadlineDates = getDeadlineDates();

	// 현재 활성화된 필터 요약
	const activeFilters = $derived(() => {
		const filters: string[] = [];

		if (filterEventStatus) {
			const opt = EVENT_STATUS_OPTIONS.find(o => o.value === filterEventStatus);
			if (opt) filters.push(opt.label);
		}

		if (filterDeadlineDate) {
			const date = deadlineDates.find(d => d.dateStr === filterDeadlineDate);
			if (date) filters.push(`${date.label} 마감`);
		}

		if (unknownPeriodFilter === 'only') {
			filters.push('기간미정만');
		} else if (unknownPeriodFilter === 'exclude') {
			filters.push('기간미정 제외');
		}

		if (filterUrlType) {
			const opt = URL_TYPE_OPTIONS.find(o => o.value === filterUrlType);
			if (opt) filters.push(opt.label);
		}

		if (filterSourceType) {
			const opt = SOURCE_TYPE_OPTIONS.find(o => o.value === filterSourceType);
			if (opt) filters.push(opt.label);
		}

		if (filterSearch) {
			filters.push(`"${filterSearch}"`);
		}

		return filters;
	});
</script>

<!-- 모바일 필터 패널 (접이식) -->
<div
	class="md:hidden mb-4 bg-white rounded-lg border border-gray-200 overflow-hidden transition-all duration-300"
	class:hidden={!showFilters}
>
	<div class="p-4 space-y-4">
		<!-- 검색 -->
		<div class="flex flex-col gap-2">
			<span class="text-sm font-medium text-gray-700">검색</span>
			<div class="relative">
				<input
					type="text"
					value={filterSearch}
					oninput={(e) => onSearchChange(e.currentTarget.value)}
					onkeydown={handleSearchKeydown}
					placeholder="제목, 요약, 주최자, 본문 검색..."
					class="w-full px-3 py-2 pr-20 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
				/>
				<div class="absolute right-1 top-1/2 -translate-y-1/2 flex gap-1">
					{#if filterSearch}
						<button
							onclick={clearSearch}
							class="p-1.5 text-gray-400 hover:text-gray-600"
							title="검색어 지우기"
						>
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					{/if}
					<button
						onclick={onSearch}
						class="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
					>
						검색
					</button>
				</div>
			</div>
		</div>

		<!-- 빠른 필터 프리셋 -->
		{#if onQuickFilter}
			<div class="flex flex-col gap-2">
				<span class="text-sm font-medium text-gray-700">빠른 필터</span>
				<div class="flex flex-wrap gap-2">
					{#each QUICK_FILTER_PRESETS as preset}
						<button
							onclick={() => applyQuickFilter(preset)}
							class="px-3 py-1.5 text-sm rounded-full bg-gradient-to-r from-gray-100 to-gray-50 text-gray-700 hover:from-blue-100 hover:to-blue-50 hover:text-blue-700 transition-colors flex items-center gap-1"
						>
							<span>{preset.icon}</span>
							<span>{preset.label}</span>
						</button>
					{/each}
				</div>
			</div>
		{/if}

		<!-- 이벤트 상태 필터 -->
		<div class="flex flex-col gap-2">
			<span class="text-sm font-medium text-gray-700">상태</span>
			<div class="flex flex-wrap gap-2">
				{#each EVENT_STATUS_OPTIONS as opt}
					{@const isActive = opt.value === '' ? filterEventStatus === null : filterEventStatus === opt.value}
					<button
						onclick={() => setEventStatusFilter(opt.value)}
						class="px-3 py-1.5 text-sm rounded-full transition-colors {isActive
							? opt.color + ' ring-2 ring-offset-1 ring-gray-400'
							: 'bg-gray-100 text-gray-600'}"
					>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>

		<!-- 마감일 날짜 필터 -->
		<div class="flex flex-col gap-2">
			<span class="text-sm font-medium text-gray-700">마감일</span>
			<div class="flex flex-wrap gap-2">
				{#each deadlineDates as { dateStr, label, dayLabel }}
					{@const count = deadlineCounts[dateStr] || 0}
					<button
						onclick={() => setDeadlineDateFilter(dateStr)}
						class="px-2.5 py-1.5 text-xs rounded-lg transition-colors flex flex-col items-center min-w-[48px] {filterDeadlineDate === dateStr
							? 'bg-indigo-100 text-indigo-700 ring-2 ring-offset-1 ring-indigo-400'
							: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
					>
						<span class="font-medium">{label}</span>
						<span class="text-[10px] opacity-70">{dayLabel}</span>
						<span class="text-[10px] mt-0.5 font-semibold {count > 0 ? 'text-indigo-600' : 'text-gray-400'}">{count}건</span>
					</button>
				{/each}
			</div>
		</div>

		<!-- 기간미정 필터 (3단계) -->
		<div class="flex flex-col gap-2">
			<span class="text-sm font-medium text-gray-700">기간 미정</span>
			<div class="flex gap-2">
				{#each UNKNOWN_PERIOD_OPTIONS as opt}
					<button
						onclick={() => setUnknownPeriodFilter(opt.value)}
						class="px-3 py-1.5 text-sm rounded-full transition-colors flex-1 {unknownPeriodFilter === opt.value
							? opt.color + ' ring-2 ring-offset-1 ring-gray-400'
							: 'bg-gray-100 text-gray-600'}"
					>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>

		<!-- 정렬 옵션 -->
		<div class="flex flex-col gap-2">
			<span class="text-sm font-medium text-gray-700">정렬</span>
			<div class="flex flex-wrap gap-2">
				{#each SORT_OPTIONS as opt}
					{@const isActive = sortBy === opt.value}
					<button
						onclick={() => handleSortChange(opt.value)}
						class="px-3 py-1.5 text-sm rounded-full transition-colors flex items-center gap-1 {isActive
							? 'bg-blue-100 text-blue-700 ring-2 ring-offset-1 ring-blue-400'
							: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
					>
						<span>{opt.icon}</span>
						<span>{opt.label}</span>
						{#if isActive}
							<span class="text-xs">{sortOrder === 'asc' ? '↑' : '↓'}</span>
						{/if}
					</button>
				{/each}
			</div>
		</div>

		<!-- 고급 필터 토글 -->
		{#if onUrlTypeChange || onSourceTypeChange}
			<button
				onclick={() => showAdvancedFilters = !showAdvancedFilters}
				class="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-800"
			>
				<svg class="w-4 h-4 transition-transform {showAdvancedFilters ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
				</svg>
				고급 필터
			</button>

			{#if showAdvancedFilters}
				<div class="space-y-3 pl-2 border-l-2 border-gray-200">
					<!-- URL 타입 필터 -->
					{#if onUrlTypeChange}
						<div class="flex flex-col gap-2">
							<span class="text-sm font-medium text-gray-600">URL 타입</span>
							<div class="flex flex-wrap gap-2">
								<button
									onclick={() => onUrlTypeChange?.(null)}
									class="px-2 py-1 text-xs rounded-full {filterUrlType === null
										? 'bg-gray-200 text-gray-700'
										: 'bg-gray-100 text-gray-500'}"
								>
									전체
								</button>
								{#each URL_TYPE_OPTIONS as opt}
									<button
										onclick={() => onUrlTypeChange?.(filterUrlType === opt.value ? null : opt.value)}
										class="px-2 py-1 text-xs rounded-full {filterUrlType === opt.value
											? 'bg-purple-100 text-purple-700'
											: 'bg-gray-100 text-gray-500'}"
									>
										{opt.label}
									</button>
								{/each}
							</div>
						</div>
					{/if}

					<!-- 출처 필터 -->
					{#if onSourceTypeChange}
						<div class="flex flex-col gap-2">
							<span class="text-sm font-medium text-gray-600">출처</span>
							<div class="flex flex-wrap gap-2">
								<button
									onclick={() => onSourceTypeChange?.(null)}
									class="px-2 py-1 text-xs rounded-full {filterSourceType === null
										? 'bg-gray-200 text-gray-700'
										: 'bg-gray-100 text-gray-500'}"
								>
									전체
								</button>
								{#each SOURCE_TYPE_OPTIONS as opt}
									<button
										onclick={() => onSourceTypeChange?.(filterSourceType === opt.value ? null : opt.value)}
										class="px-2 py-1 text-xs rounded-full {filterSourceType === opt.value
											? 'bg-teal-100 text-teal-700'
											: 'bg-gray-100 text-gray-500'}"
									>
										{opt.label}
									</button>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- 닫기 버튼 -->
		<div class="pt-2 border-t border-gray-100">
			<button onclick={() => onShowFiltersChange(false)} class="w-full btn btn-secondary btn-sm">
				닫기
			</button>
		</div>
	</div>
</div>

<!-- 데스크톱 필터 영역 -->
<div class="hidden md:block mb-4 space-y-3">
	<!-- 현재 필터 상태 요약 (활성 필터가 있을 때만) -->
	{#if activeFilters().length > 0}
		<div class="flex items-center gap-2 p-2 bg-blue-50 rounded-lg">
			<span class="text-xs text-blue-600 font-medium">활성 필터:</span>
			<div class="flex flex-wrap gap-1">
				{#each activeFilters() as filter}
					<span class="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded-full">{filter}</span>
				{/each}
			</div>
		</div>
	{/if}

	<!-- 첫 번째 줄: 검색 + 빠른 필터 -->
	<div class="flex items-center gap-3">
		<!-- 검색 입력 -->
		<div class="relative flex-1 max-w-md">
			<input
				type="text"
				value={filterSearch}
				oninput={(e) => onSearchChange(e.currentTarget.value)}
				onkeydown={handleSearchKeydown}
				placeholder="제목, 요약, 주최자, 본문 검색..."
				class="w-full px-3 py-1.5 pr-20 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
			/>
			<div class="absolute right-1 top-1/2 -translate-y-1/2 flex gap-1">
				{#if filterSearch}
					<button
						onclick={clearSearch}
						class="p-1 text-gray-400 hover:text-gray-600"
						title="검색어 지우기"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				{/if}
				<button
					onclick={onSearch}
					class="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
				>
					검색
				</button>
			</div>
		</div>

		<!-- 빠른 필터 프리셋 -->
		{#if onQuickFilter}
			<div class="flex gap-2">
				{#each QUICK_FILTER_PRESETS as preset}
					<button
						onclick={() => applyQuickFilter(preset)}
						class="px-3 py-1.5 text-sm rounded-full bg-gradient-to-r from-gray-100 to-gray-50 text-gray-700 hover:from-blue-100 hover:to-blue-50 hover:text-blue-700 transition-colors flex items-center gap-1 whitespace-nowrap"
						title={preset.label}
					>
						<span>{preset.icon}</span>
						<span class="hidden lg:inline">{preset.label}</span>
					</button>
				{/each}
			</div>
		{/if}
	</div>

	<!-- 두 번째 줄: 이벤트 상태 + 기간미정 필터 + 정렬 -->
	<div class="flex flex-wrap gap-2 items-center">
		<span class="text-sm text-gray-500">상태:</span>
		{#each EVENT_STATUS_OPTIONS as opt}
			{@const isActive = opt.value === '' ? filterEventStatus === null : filterEventStatus === opt.value}
			<button
				onclick={() => setEventStatusFilter(opt.value)}
				class="px-3 py-1 text-sm rounded-full transition-colors {isActive
					? opt.color + ' ring-2 ring-offset-1 ring-gray-400'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
			>
				{opt.label}
			</button>
		{/each}

		<span class="text-gray-300 mx-1">|</span>

		<!-- 기간미정 필터 (3단계) -->
		<span class="text-sm text-gray-500">기간미정:</span>
		{#each UNKNOWN_PERIOD_OPTIONS as opt}
			<button
				onclick={() => setUnknownPeriodFilter(opt.value)}
				class="px-2 py-1 text-xs rounded-full transition-colors {unknownPeriodFilter === opt.value
					? opt.color + ' ring-2 ring-offset-1 ring-gray-400'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
			>
				{opt.label}
			</button>
		{/each}

		<span class="text-gray-300 mx-1">|</span>

		<!-- 정렬 옵션 -->
		<span class="text-sm text-gray-500">정렬:</span>
		{#each SORT_OPTIONS as opt}
			{@const isActive = sortBy === opt.value}
			<button
				onclick={() => handleSortChange(opt.value)}
				class="px-2 py-1 text-xs rounded-full transition-colors flex items-center gap-1 {isActive
					? 'bg-blue-100 text-blue-700 ring-1 ring-blue-400'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
			>
				<span>{opt.icon}</span>
				<span>{opt.label}</span>
				{#if isActive}
					<span>{sortOrder === 'asc' ? '↑' : '↓'}</span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- 세 번째 줄: 마감일 날짜 필터 -->
	<div class="flex flex-wrap gap-2 items-center">
		<span class="text-sm text-gray-500">마감일:</span>
		{#each deadlineDates as { dateStr, label, dayLabel }}
			{@const count = deadlineCounts[dateStr] || 0}
			<button
				onclick={() => setDeadlineDateFilter(dateStr)}
				class="px-2.5 py-1 text-sm rounded-lg transition-colors flex items-center gap-1.5 {filterDeadlineDate === dateStr
					? 'bg-indigo-100 text-indigo-700 ring-2 ring-offset-1 ring-indigo-400'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
			>
				<span class="font-medium">{label}</span>
				<span class="text-xs opacity-70">({dayLabel})</span>
				<span class="text-xs font-semibold {count > 0 ? 'text-indigo-600' : 'text-gray-400'}">{count}건</span>
			</button>
		{/each}

		<!-- 고급 필터 토글 -->
		{#if onUrlTypeChange || onSourceTypeChange}
			<span class="text-gray-300 mx-1">|</span>
			<button
				onclick={() => showAdvancedFilters = !showAdvancedFilters}
				class="px-2 py-1 text-xs rounded-full transition-colors flex items-center gap-1 {showAdvancedFilters
					? 'bg-gray-200 text-gray-700'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
			>
				<svg class="w-3 h-3 transition-transform {showAdvancedFilters ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
				</svg>
				고급
			</button>
		{/if}
	</div>

	<!-- 고급 필터 (URL 타입, 출처) -->
	{#if showAdvancedFilters && (onUrlTypeChange || onSourceTypeChange)}
		<div class="flex flex-wrap gap-4 items-center p-2 bg-gray-50 rounded-lg">
			<!-- URL 타입 필터 -->
			{#if onUrlTypeChange}
				<div class="flex items-center gap-2">
					<span class="text-sm text-gray-500">URL:</span>
					<button
						onclick={() => onUrlTypeChange?.(null)}
						class="px-2 py-0.5 text-xs rounded-full {filterUrlType === null
							? 'bg-gray-200 text-gray-700'
							: 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
					>
						전체
					</button>
					{#each URL_TYPE_OPTIONS as opt}
						<button
							onclick={() => onUrlTypeChange?.(filterUrlType === opt.value ? null : opt.value)}
							class="px-2 py-0.5 text-xs rounded-full {filterUrlType === opt.value
								? 'bg-purple-100 text-purple-700'
								: 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
						>
							{opt.label}
						</button>
					{/each}
				</div>
			{/if}

			<!-- 출처 필터 -->
			{#if onSourceTypeChange}
				<div class="flex items-center gap-2">
					<span class="text-sm text-gray-500">출처:</span>
					<button
						onclick={() => onSourceTypeChange?.(null)}
						class="px-2 py-0.5 text-xs rounded-full {filterSourceType === null
							? 'bg-gray-200 text-gray-700'
							: 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
					>
						전체
					</button>
					{#each SOURCE_TYPE_OPTIONS as opt}
						<button
							onclick={() => onSourceTypeChange?.(filterSourceType === opt.value ? null : opt.value)}
							class="px-2 py-0.5 text-xs rounded-full {filterSourceType === opt.value
								? 'bg-teal-100 text-teal-700'
								: 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
						>
							{opt.label}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
