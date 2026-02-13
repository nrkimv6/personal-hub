<script lang="ts">
	import { onMount } from 'svelte';
	import { Button } from '$lib/components/ui';
	import { goto } from '$app/navigation';
  import { fetchWithTimeout } from '$lib/api/client';

	type Report = {
		id: number;
		report_type: string;
		period_start: string;
		period_end: string;
		title: string | null;
		summary: string | null;
		generated_at: string;
		format: string;
	};

	type ReportList = {
		items: Report[];
		total: number;
		page: number;
		page_size: number;
		total_pages: number;
	};

	let reports: Report[] = $state([]);
	let total = $state(0);
	let totalPages = $state(0);
	let currentPage = $state(1);
	let pageSize = 20;
	let loading = $state(true);
	let error: string | null = $state(null);

	// 필터
	let filterReportType: string | null = $state(null);
	let filterSearch = $state('');

	const reportTypeNames: Record<string, string> = {
		nightly_cleanup: 'WTools 아카이빙',
		sleep_now: '수면 시스템',
		daily_summary: '일일 요약'
	};

	async function loadReports() {
		loading = true;
		error = null;

		try {
			const params = new URLSearchParams({
				page: currentPage.toString(),
				page_size: pageSize.toString(),
				sort_by: 'generated_at',
				sort_order: 'desc'
			});

			if (filterReportType) {
				params.append('report_type', filterReportType);
			}

			if (filterSearch) {
				params.append('search', filterSearch);
			}

			const response = await fetchWithTimeout(`/api/v1/reports?${params}`);

			if (!response.ok) {
				throw new Error(`Failed to load reports: ${response.statusText}`);
			}

			const data: ReportList = await response.json();
			reports = data.items;
			total = data.total;
			totalPages = data.total_pages;
		} catch (err) {
			error = err instanceof Error ? err.message : 'Unknown error';
		} finally {
			loading = false;
		}
	}

	function formatDate(dateStr: string): string {
		const date = new Date(dateStr);
		return date.toLocaleString('ko-KR', {
			year: 'numeric',
			month: '2-digit',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatPeriod(start: string, end: string): string {
		const startDate = new Date(start);
		const endDate = new Date(end);

		if (startDate.toDateString() === endDate.toDateString()) {
			return endDate.toLocaleDateString('ko-KR');
		}

		return `${startDate.toLocaleDateString('ko-KR')} ~ ${endDate.toLocaleDateString('ko-KR')}`;
	}

	function viewReport(reportId: number) {
		goto(`/reports/${reportId}`);
	}

	function resetFilters() {
		filterReportType = null;
		filterSearch = '';
		currentPage = 1;
		loadReports();
	}

	function applyFilters() {
		currentPage = 1;
		loadReports();
	}

	function nextPage() {
		if (currentPage < totalPages) {
			currentPage++;
			loadReports();
		}
	}

	function prevPage() {
		if (currentPage > 1) {
			currentPage--;
			loadReports();
		}
	}

	onMount(() => {
		loadReports();
	});
</script>

<div>
	<div class="mb-6">
		<h2 class="text-lg font-bold text-neutral-800 dark:text-neutral-100">LLM 보고서</h2>
		<p class="text-sm text-neutral-600 dark:text-neutral-400 mt-1">
			시스템에서 자동 생성된 보고서를 조회합니다.
		</p>
	</div>

	<!-- 필터 -->
	<div class="bg-white dark:bg-neutral-800 rounded-lg shadow-sm p-4 mb-4">
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
			<!-- 보고서 타입 -->
			<div>
				<label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
					보고서 타입
				</label>
				<select
					bind:value={filterReportType}
					class="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-md bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
				>
					<option value={null}>전체</option>
					<option value="nightly_cleanup">WTools 아카이빙</option>
					<option value="sleep_now">수면 시스템</option>
					<option value="daily_summary">일일 요약</option>
				</select>
			</div>

			<!-- 검색 -->
			<div>
				<label class="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
					검색
				</label>
				<input
					type="text"
					bind:value={filterSearch}
					placeholder="제목 또는 요약..."
					class="w-full px-3 py-2 border border-neutral-300 dark:border-neutral-600 rounded-md bg-white dark:bg-neutral-700 text-neutral-900 dark:text-neutral-100"
				/>
			</div>

			<!-- 버튼 -->
			<div class="flex items-end gap-2">
				<Button onclick={applyFilters} class="flex-1">조회</Button>
				<Button onclick={resetFilters} variant="outline" class="flex-1">초기화</Button>
			</div>
		</div>
	</div>

	<!-- 로딩 상태 -->
	{#if loading}
		<div class="text-center py-12">
			<div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-neutral-300 border-t-brand-500"></div>
			<p class="mt-2 text-neutral-600 dark:text-neutral-400">보고서를 불러오는 중...</p>
		</div>
	{:else if error}
		<div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
			<p class="text-red-800 dark:text-red-200">{error}</p>
		</div>
	{:else if reports.length === 0}
		<div class="bg-neutral-50 dark:bg-neutral-800 rounded-lg p-12 text-center">
			<p class="text-neutral-600 dark:text-neutral-400">보고서가 없습니다.</p>
		</div>
	{:else}
		<!-- 보고서 목록 -->
		<div class="bg-white dark:bg-neutral-800 rounded-lg shadow-sm overflow-hidden">
			<table class="w-full">
				<thead class="bg-neutral-50 dark:bg-neutral-700">
					<tr>
						<th class="px-6 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
							타입
						</th>
						<th class="px-6 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
							제목
						</th>
						<th class="px-6 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
							기간
						</th>
						<th class="px-6 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
							생성일시
						</th>
						<th class="px-6 py-3 text-left text-xs font-medium text-neutral-500 dark:text-neutral-400 uppercase tracking-wider">
							작업
						</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-neutral-200 dark:divide-neutral-700">
					{#each reports as report}
						<tr class="hover:bg-neutral-50 dark:hover:bg-neutral-700/50 cursor-pointer" onclick={() => viewReport(report.id)}>
							<td class="px-6 py-4 whitespace-nowrap">
								<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-brand-100 text-brand-800 dark:bg-brand-900/30 dark:text-brand-300">
									{reportTypeNames[report.report_type] || report.report_type}
								</span>
							</td>
							<td class="px-6 py-4">
								<div class="text-sm font-medium text-neutral-900 dark:text-neutral-100">
									{report.title || '제목 없음'}
								</div>
								{#if report.summary}
									<div class="text-xs text-neutral-500 dark:text-neutral-400 mt-1 line-clamp-1">
										{report.summary}
									</div>
								{/if}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-neutral-600 dark:text-neutral-400">
								{formatPeriod(report.period_start, report.period_end)}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm text-neutral-600 dark:text-neutral-400">
								{formatDate(report.generated_at)}
							</td>
							<td class="px-6 py-4 whitespace-nowrap text-sm">
								<Button onclick={() => viewReport(report.id)} variant="outline" size="sm">
									보기
								</Button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- 페이지네이션 -->
		<div class="mt-4 flex items-center justify-between">
			<div class="text-sm text-neutral-600 dark:text-neutral-400">
				전체 {total}개 중 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)}개 표시
			</div>
			<div class="flex gap-2">
				<Button onclick={prevPage} disabled={currentPage === 1} variant="outline">
					이전
				</Button>
				<span class="px-4 py-2 text-neutral-700 dark:text-neutral-300">
					{currentPage} / {totalPages}
				</span>
				<Button onclick={nextPage} disabled={currentPage === totalPages} variant="outline">
					다음
				</Button>
			</div>
		</div>
	{/if}
</div>
