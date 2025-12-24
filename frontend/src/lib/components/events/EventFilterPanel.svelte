<script lang="ts">
	/**
	 * 이벤트/팝업 필터 패널 컴포넌트
	 *
	 * 모바일(접이식)과 데스크톱(인라인) 필터 UI 제공
	 */
	import { EVENT_STATUS_OPTIONS } from '$lib/constants/eventConstants';

	interface Props {
		filterEventStatus: string | null;
		filterBookmarked: boolean | null;
		includeUnknownPeriod: boolean;
		showFilters: boolean;
		onStatusFilterChange: (status: string | null) => void;
		onBookmarkedFilterToggle: () => void;
		onUnknownPeriodToggle: () => void;
		onShowFiltersChange: (show: boolean) => void;
	}

	let {
		filterEventStatus,
		filterBookmarked,
		includeUnknownPeriod,
		showFilters,
		onStatusFilterChange,
		onBookmarkedFilterToggle,
		onUnknownPeriodToggle,
		onShowFiltersChange
	}: Props = $props();

	function setEventStatusFilter(status: string) {
		onStatusFilterChange(filterEventStatus === status ? null : status);
	}
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
			<label class="flex items-center gap-2 cursor-pointer">
				<input
					type="checkbox"
					checked={filterBookmarked === true}
					onchange={onBookmarkedFilterToggle}
					class="w-4 h-4 text-yellow-600 rounded border-gray-300 focus:ring-yellow-500"
				/>
				<span class="text-sm text-gray-600">북마크만</span>
			</label>
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
<div class="hidden md:flex mb-4 flex-wrap gap-2 items-center">
	<!-- 이벤트 상태 필터 -->
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

	<!-- 북마크만 -->
	<label class="flex items-center gap-2 cursor-pointer">
		<input
			type="checkbox"
			checked={filterBookmarked === true}
			onchange={onBookmarkedFilterToggle}
			class="w-4 h-4 text-yellow-600 rounded border-gray-300 focus:ring-yellow-500"
		/>
		<span class="text-sm text-gray-600">북마크만</span>
	</label>
</div>
