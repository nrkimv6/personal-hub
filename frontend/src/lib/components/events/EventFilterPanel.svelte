<script lang="ts">
	/**
	 * 이벤트/팝업 필터 패널 컴포넌트
	 *
	 * 모바일(접이식)과 데스크톱(인라인) 필터 UI 제공
	 * 날짜별 마감일 필터 (오늘부터 6일간) 지원
	 */
	import { EVENT_STATUS_OPTIONS } from '$lib/constants/eventConstants';

	interface Props {
		filterEventStatus: string | null;
		filterBookmarked: boolean | null;
		includeUnknownPeriod: boolean;
		showFilters: boolean;
		// 날짜별 마감 필터
		filterDeadlineDate: string | null;
		deadlineCounts: Record<string, number>;
		// 검색
		filterSearch: string;
		onStatusFilterChange: (status: string | null) => void;
		onBookmarkedFilterToggle: () => void;
		onUnknownPeriodToggle: () => void;
		onShowFiltersChange: (show: boolean) => void;
		onDeadlineDateChange: (date: string | null) => void;
		onSearchChange: (search: string) => void;
		onSearch: () => void;
	}

	let {
		filterEventStatus,
		filterBookmarked,
		includeUnknownPeriod,
		showFilters,
		filterDeadlineDate = null,
		deadlineCounts = {},
		filterSearch = '',
		onStatusFilterChange,
		onBookmarkedFilterToggle,
		onUnknownPeriodToggle,
		onShowFiltersChange,
		onDeadlineDateChange,
		onSearchChange,
		onSearch
	}: Props = $props();

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
		onStatusFilterChange(filterEventStatus === status ? null : status);
	}

	function setDeadlineDateFilter(dateStr: string) {
		onDeadlineDateChange(filterDeadlineDate === dateStr ? null : dateStr);
	}

	// 오늘부터 6일간 날짜 배열 생성 (로컬 타임존 기준)
	function getDeadlineDates(): { dateStr: string; label: string; dayLabel: string }[] {
		const dates: { dateStr: string; label: string; dayLabel: string }[] = [];
		const today = new Date();
		const dayNames = ['일', '월', '화', '수', '목', '금', '토'];

		for (let i = 0; i < 6; i++) {
			const d = new Date(today);
			d.setDate(today.getDate() + i);
			// 로컬 타임존 기준 YYYY-MM-DD (toISOString()은 UTC 기준이라 하루 밀림)
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
</script>

<!-- 모바일 필터 패널 (접이식) -->
<div
	class="md:hidden mb-4 bg-white rounded-lg border border-gray-200 overflow-hidden transition-all duration-300"
	class:hidden={!showFilters}
>
	<div class="p-4 space-y-4">
		<!-- 검색 -->
		<div class="flex flex-col gap-2">
			<label class="text-sm font-medium text-gray-700">검색</label>
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

		<!-- 이벤트 상태 필터 -->
		<div class="flex flex-col gap-2">
			<label class="text-sm font-medium text-gray-700">상태</label>
			<div class="flex flex-wrap gap-2">
				{#each EVENT_STATUS_OPTIONS as opt}
					<button
						onclick={() => setEventStatusFilter(opt.value)}
						class="px-3 py-1.5 text-sm rounded-full transition-colors {filterEventStatus ===
						opt.value
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
			<label class="text-sm font-medium text-gray-700">마감일</label>
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

		<!-- 옵션 체크박스 -->
		<div class="flex flex-col gap-3">
			<label class="flex items-center gap-2 cursor-pointer">
				<input
					type="checkbox"
					checked={includeUnknownPeriod}
					onchange={onUnknownPeriodToggle}
					class="w-4 h-4 text-amber-600 rounded border-gray-300 focus:ring-amber-500"
				/>
				<span class="text-sm text-gray-600">기간 미정 포함</span>
			</label>
			<!-- 북마크 기능 임시 비활성화
			<label class="flex items-center gap-2 cursor-pointer">
				<input
					type="checkbox"
					checked={filterBookmarked === true}
					onchange={onBookmarkedFilterToggle}
					class="w-4 h-4 text-yellow-600 rounded border-gray-300 focus:ring-yellow-500"
				/>
				<span class="text-sm text-gray-600">북마크만</span>
			</label> -->
		</div>

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
	<!-- 검색 입력 -->
	<div class="flex items-center gap-3">
		<span class="text-sm text-gray-500">검색:</span>
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
	</div>

	<!-- 첫 번째 줄: 이벤트 상태 필터 -->
	<div class="flex flex-wrap gap-2 items-center">
		<span class="text-sm text-gray-500">상태:</span>
		{#each EVENT_STATUS_OPTIONS as opt}
			<button
				onclick={() => setEventStatusFilter(opt.value)}
				class="px-3 py-1 text-sm rounded-full transition-colors {filterEventStatus === opt.value
					? opt.color + ' ring-2 ring-offset-1 ring-gray-400'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
			>
				{opt.label}
			</button>
		{/each}

		<span class="text-gray-300 mx-1">|</span>

		<!-- 기간 미정 포함 -->
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={includeUnknownPeriod}
				onchange={onUnknownPeriodToggle}
				class="w-4 h-4 text-amber-600 rounded border-gray-300 focus:ring-amber-500"
			/>
			<span class="text-sm text-gray-600">기간 미정 포함</span>
		</label>

		<!-- 북마크 기능 임시 비활성화
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={filterBookmarked === true}
				onchange={onBookmarkedFilterToggle}
				class="w-4 h-4 text-yellow-600 rounded border-gray-300 focus:ring-yellow-500"
			/>
			<span class="text-sm text-gray-600">북마크만</span>
		</label> -->
	</div>

	<!-- 두 번째 줄: 마감일 날짜 필터 -->
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
	</div>
</div>
