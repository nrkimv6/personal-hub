<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from '$lib/stores/toast';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import { buildMonitoringHref } from '$lib/utils/monitoringRouteState';
	import {
		activityApi,
		formatActivityCenterType,
		type ActivityCenter,
		type ActivityCourse,
		type ActivityCrawlRequest,
		type ActivityWorkerStatus
	} from '$lib/api/activity';

	interface Props {
		view?: string | null;
		sub?: string | null;
		unified?: boolean;
	}

	let { view = null, sub = null, unified = false }: Props = $props();

	// 탭 상태
	type ActivityTab = 'centers' | 'courses';
	function normalizeActivityTab(tab: string | null | undefined): ActivityTab {
		return tab === 'courses' ? 'courses' : 'centers';
	}

	let activeTab: ActivityTab = $state(normalizeActivityTab(view ?? sub));

	// 공통 상태
	let loading = $state(true);
	let error = $state('');

	// 센터 관련 상태
	let workerStatus: ActivityWorkerStatus | null = $state(null);
	let centers: ActivityCenter[] = $state([]);
	let requests: ActivityCrawlRequest[] = $state([]);
	let syncing = $state(false);

	// 강좌 관련 상태
	let courses: ActivityCourse[] = $state([]);
	let courseTotal = $state(0);
	let coursePage = $state(1);
	let coursePageSize = $state(20);
	let courseKeyword = $state('');
	let courseCategory = $state('');

	// Activity-Hub 수동 동기화
	async function syncToActivityHub() {
		syncing = true;
		try {
			await activityApi.syncToActivityHub();
			toast.success('Activity-Hub 동기화가 시작되었습니다.');
			setTimeout(() => loadWorkerStatus(), 2000);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '동기화 요청 실패');
		} finally {
			syncing = false;
		}
	}

	// 워커 상태 로드
	async function loadWorkerStatus() {
		try {
			workerStatus = await activityApi.getWorkerStatus();
		} catch (e) {
			console.error('워커 상태 로드 실패:', e);
		}
	}

	// 센터 목록 로드
	async function loadCenters() {
		try {
			const response = await activityApi.listCenters({ page_size: 50 });
			centers = response.items;
		} catch (e) {
			console.error('센터 목록 로드 실패:', e);
		}
	}

	// 요청 목록 로드
	async function loadRequests() {
		try {
			requests = await activityApi.listRequests(10);
		} catch (e) {
			console.error('요청 목록 로드 실패:', e);
		}
	}

	// 강좌 목록 로드
	async function loadCourses() {
		try {
			const response = await activityApi.listCourses({
				page: coursePage,
				page_size: coursePageSize,
				keyword: courseKeyword || undefined,
				category: courseCategory || undefined
			});
			courses = response.items;
			courseTotal = response.total;
		} catch (e) {
			console.error('강좌 목록 로드 실패:', e);
		}
	}

	// 크롤링 요청 생성
	async function requestCrawl(centerId: number) {
		try {
			await activityApi.requestCrawl(centerId);
			await loadRequests();
			await loadWorkerStatus();
		} catch (e) {
			error = e instanceof Error ? e.message : '요청 실패';
		}
	}

	// 강좌 검색
	async function searchCourses() {
		coursePage = 1;
		await loadCourses();
	}

	function formatDate(dateStr: string | null | undefined): string {
		if (!dateStr) return '-';
		return new Date(dateStr).toLocaleString('ko-KR', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatSimpleDate(dateStr: string | null | undefined): string {
		if (!dateStr) return '-';
		return new Date(dateStr).toLocaleDateString('ko-KR', {
			month: 'short',
			day: 'numeric'
		});
	}

	function getStatusBadge(status: string): { bg: string; text: string; label: string } {
		switch (status) {
			case 'pending':
				return { bg: 'bg-warning-light', text: 'text-warning-foreground', label: '대기' };
			case 'picked':
			case 'processing':
				return { bg: 'bg-primary-light', text: 'text-primary', label: '처리중' };
			case 'completed':
				return { bg: 'bg-success-light', text: 'text-success', label: '완료' };
			case 'failed':
				return { bg: 'bg-error-light', text: 'text-error', label: '실패' };
			default:
				return { bg: 'bg-muted', text: 'text-foreground', label: status };
		}
	}

	function getCategoryName(cat: string | null | undefined): string {
		if (!cat) return '-';
		const categories: Record<string, string> = {
			exercise: '운동/건강',
			art: '미술/공예',
			music: '음악',
			cooking: '요리',
			language: '어학',
			hobby: '취미/교양',
			certificate: '자격증',
			other: '기타'
		};
		return categories[cat] || cat;
	}

	function formatFee(fee: number | null | undefined): string {
		if (fee === null || fee === undefined) return '-';
		return `${fee.toLocaleString()}원`;
	}

	// 탭 변경 시 강좌 lazy loading
	$effect(() => {
		if (activeTab === 'courses' && courses.length === 0) {
			loadCourses();
		}
	});

	$effect(() => {
		if (!unified) return;
		activeTab = normalizeActivityTab(view ?? sub);
	});

	function handleActivityTabChange(tabId: string) {
		const next = normalizeActivityTab(tabId);
		activeTab = next;
		if (!unified) return;
		goto(buildMonitoringHref({ type: 'activity', view: next }, $page.url), {
			replaceState: true,
			keepFocus: true,
			noScroll: true
		});
	}

	// 페이지 변경
	async function changePage(newPage: number) {
		coursePage = newPage;
		await loadCourses();
	}

	onMount(async () => {
		loading = true;
		await Promise.all([loadWorkerStatus(), loadCenters(), loadRequests()]);
		loading = false;
	});

	// 총 페이지 수 계산
	const totalPages = $derived(Math.ceil(courseTotal / coursePageSize));

	// 탭 목록 (강좌 카운트 동적 반영)
	const activityTabs = $derived([
		{ id: 'centers', label: '문화센터' },
		{ id: 'courses', label: courseTotal ? `강좌 목록 (${courseTotal})` : '강좌 목록' },
	]);
</script>

<svelte:head>
	<title>문화/체육센터 | Monitor Page</title>
</svelte:head>

{#snippet pageNavigation()}
	<TabNav
		tabs={activityTabs}
		bind:activeTab
		variant="primary"
		level="primary"
		queryParam={unified ? undefined : 'tab'}
		size="header"
		overflow="scroll"
		onTabChange={handleActivityTabChange}
	/>
{/snippet}

<div class="p-4 space-y-4">
	<PageHeader title="문화/체육센터 강좌" navigation={pageNavigation} />

	{#if error}
		<div class="mb-4 rounded-lg bg-error-light p-4 text-error">{error}</div>
	{/if}

	{#if loading}
		<div class="text-muted-foreground">로딩 중...</div>
	{:else if activeTab === 'centers'}
		<!-- 센터 관리 탭 -->
		<div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
			<!-- 워커 상태 카드 -->
			<div class="rounded-lg bg-white p-4 shadow">
				<h2 class="mb-4 text-lg font-semibold">워커 상태</h2>

				{#if workerStatus}
					<div class="space-y-3">
						<div class="flex items-center justify-between">
							<span class="text-muted-foreground">상태</span>
							{#if workerStatus.is_running}
								<span class="rounded bg-success-light px-2 py-1 text-sm text-success">실행 중</span>
							{:else}
								<span class="rounded bg-muted px-2 py-1 text-sm text-muted-foreground">대기</span>
							{/if}
						</div>
						<div class="flex items-center justify-between">
							<span class="text-muted-foreground">대기 요청</span>
							<span class="font-medium">{workerStatus.pending_requests}</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-muted-foreground">처리 중</span>
							<span class="font-medium">{workerStatus.processing_requests}</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-muted-foreground">24시간 크롤링</span>
							<span class="font-medium">{workerStatus.recent_runs}회</span>
						</div>
						{#if workerStatus.last_activity}
							<div class="flex items-center justify-between">
								<span class="text-muted-foreground">마지막 활동</span>
								<span class="text-sm">{formatDate(workerStatus.last_activity)}</span>
							</div>
						{/if}

						<!-- Activity-Hub 수동 동기화 버튼 -->
						<button
							onclick={syncToActivityHub}
							disabled={syncing}
							class="mt-4 w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
						>
							{#if syncing}
								<span class="flex items-center justify-center gap-2">
									<svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24">
										<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
										<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
									</svg>
									동기화 중...
								</span>
							{:else}
								Activity-Hub 동기화
							{/if}
						</button>
					</div>
				{:else}
					<div class="text-muted-foreground">워커 상태를 가져올 수 없습니다.</div>
				{/if}
			</div>

			<!-- 최근 요청 카드 -->
			<div class="rounded-lg bg-white p-4 shadow lg:col-span-2">
				<h2 class="mb-4 text-lg font-semibold">최근 크롤링 요청</h2>

				{#if requests.length === 0}
					<div class="text-muted-foreground">요청 내역이 없습니다.</div>
				{:else}
					<div class="overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b text-left text-muted-foreground">
									<th class="pb-2">ID</th>
									<th class="pb-2">URL</th>
									<th class="pb-2">상태</th>
									<th class="pb-2">요청시간</th>
								</tr>
							</thead>
							<tbody>
								{#each requests as req}
									{@const badge = getStatusBadge(req.status)}
									<tr class="border-b">
										<td class="py-2">{req.id}</td>
										<td class="max-w-48 truncate py-2" title={req.url}>{req.url}</td>
										<td class="py-2">
											<span class="rounded px-2 py-0.5 {badge.bg} {badge.text}">
												{badge.label}
											</span>
										</td>
										<td class="py-2 text-muted-foreground">{formatDate(req.requested_at)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>

		<!-- 센터 목록 -->
		<div class="mt-6 rounded-lg bg-white p-4 shadow">
			<h2 class="mb-4 text-lg font-semibold">등록된 센터 ({centers.length})</h2>

			{#if centers.length === 0}
				<div class="text-muted-foreground">등록된 센터가 없습니다.</div>
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b text-left text-muted-foreground">
								<th class="pb-2">ID</th>
								<th class="pb-2">이름</th>
								<th class="pb-2">유형</th>
								<th class="pb-2">크롤링 방식</th>
								<th class="pb-2">마지막 크롤링</th>
								<th class="pb-2">상태</th>
								<th class="pb-2">작업</th>
							</tr>
						</thead>
						<tbody>
							{#each centers as center}
								<tr class="border-b hover:bg-muted">
									<td class="py-2">{center.id}</td>
									<td class="py-2 font-medium">{center.name}</td>
									<td class="py-2">{formatActivityCenterType(center.center_type)}</td>
									<td class="py-2">{center.crawl_method}</td>
									<td class="py-2 text-muted-foreground">{formatDate(center.last_crawled_at)}</td>
									<td class="py-2">
										{#if center.is_active}
											<span class="rounded bg-success-light px-2 py-0.5 text-success">활성</span>
										{:else}
											<span class="rounded bg-muted px-2 py-0.5 text-muted-foreground">비활성</span>
										{/if}
									</td>
									<td class="py-2">
										<button
											onclick={() => requestCrawl(center.id)}
											disabled={!center.is_active}
											class="rounded bg-primary px-3 py-1 text-white hover:bg-primary-hover disabled:opacity-50"
										>
											크롤링
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	{:else}
		<!-- 강좌 목록 탭 -->
		<div class="rounded-lg bg-white p-4 shadow">
			<!-- 검색 필터 -->
			<div class="mb-4 flex flex-wrap gap-4">
				<input
					type="text"
					bind:value={courseKeyword}
					placeholder="강좌명 검색..."
					class="rounded border px-3 py-2 text-sm"
					onkeydown={(e) => e.key === 'Enter' && searchCourses()}
				/>
				<select
					bind:value={courseCategory}
					class="rounded border px-3 py-2 text-sm"
					onchange={searchCourses}
				>
					<option value="">전체 카테고리</option>
					<option value="exercise">운동/건강</option>
					<option value="art">미술/공예</option>
					<option value="music">음악</option>
					<option value="cooking">요리</option>
					<option value="language">어학</option>
					<option value="hobby">취미/교양</option>
					<option value="other">기타</option>
				</select>
				<button onclick={searchCourses} class="rounded bg-primary px-4 py-2 text-sm text-white hover:bg-primary-hover">
					검색
				</button>
			</div>

			<!-- 강좌 테이블 -->
			{#if courses.length === 0}
				<div class="py-8 text-center text-muted-foreground">
					{courseKeyword || courseCategory ? '검색 결과가 없습니다.' : '수집된 강좌가 없습니다.'}
				</div>
			{:else}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b text-left text-muted-foreground">
								<th class="pb-2">강좌명</th>
								<th class="pb-2">센터</th>
								<th class="pb-2">카테고리</th>
								<th class="pb-2">요일/시간</th>
								<th class="pb-2">기간</th>
								<th class="pb-2">강사</th>
								<th class="pb-2">수강료</th>
							</tr>
						</thead>
						<tbody>
							{#each courses as course}
								<tr class="border-b hover:bg-muted">
									<td class="max-w-64 truncate py-2 font-medium" title={course.name}>
										{#if course.source_url}
											<a
												href={course.source_url}
												target="_blank"
												class="text-primary hover:underline"
											>
												{course.name}
											</a>
										{:else}
											{course.name}
										{/if}
									</td>
									<td class="py-2 text-muted-foreground">{course.center_name || '-'}</td>
									<td class="py-2">{getCategoryName(course.category)}</td>
									<td class="py-2">
										{course.day_of_week || '-'}
										{#if course.time_start}
											<span class="text-muted-foreground">{course.time_start}~{course.time_end}</span>
										{/if}
									</td>
									<td class="py-2 text-muted-foreground">
										{formatSimpleDate(course.course_start)} ~ {formatSimpleDate(course.course_end)}
									</td>
									<td class="py-2">{course.instructor_name || '-'}</td>
									<td class="py-2">{formatFee(course.fee)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- 페이지네이션 -->
				{#if totalPages > 1}
					<div class="mt-4 flex items-center justify-between">
						<div class="text-sm text-muted-foreground">
							총 {courseTotal}개 중 {(coursePage - 1) * coursePageSize + 1}-{Math.min(
								coursePage * coursePageSize,
								courseTotal
							)}
						</div>
						<div class="flex gap-2">
							<button
								onclick={() => changePage(coursePage - 1)}
								disabled={coursePage <= 1}
								class="rounded border px-3 py-1 text-sm disabled:opacity-50"
							>
								이전
							</button>
							<span class="px-3 py-1 text-sm">{coursePage} / {totalPages}</span>
							<button
								onclick={() => changePage(coursePage + 1)}
								disabled={coursePage >= totalPages}
								class="rounded border px-3 py-1 text-sm disabled:opacity-50"
							>
								다음
							</button>
						</div>
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>
