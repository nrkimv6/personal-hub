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
		onStatusFilterChange: (status: string | null) => void;
		onBookmarkedFilterToggle: () => void;
		onUnknownPeriodToggle: () => void;
		onShowFiltersChange: (show: boolean) => void;
		onDeadlineDateChange: (date: string | null) => void;
	}

	let {
		filterEventStatus,
		filterBookmarked,
		includeUnknownPeriod,
		showFilters,
		filterDeadlineDate = null,
		deadlineCounts = {},
		onStatusFilterChange,
		onBookmarkedFilterToggle,
		onUnknownPeriodToggle,
		onShowFiltersChange,
		onDeadlineDateChange
	}: Props = $props();

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
