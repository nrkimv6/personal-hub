<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { instagramApi } from '$lib/api';
	import type {
		InstagramStats,
		InstagramCrawlRun,
		InstagramTodayScheduleItem,
		InstagramCrawlRequest
	} from '$lib/types';
	import WorkerStatusCard from '$lib/components/instagram/WorkerStatusCard.svelte';
	import TagManager from '$lib/components/instagram/TagManager.svelte';

	// 탭 상태
	let activeTab: 'dashboard' | 'tags' = 'dashboard';

	// URL 파라미터에서 탭 초기화
	$: {
		const tab = $page.url.searchParams.get('tab');
		if (tab === 'tags') {
			activeTab = tab;
		}
	}

	let stats: InstagramStats | null = null;
	let recentRuns: InstagramCrawlRun[] = [];
	let todaySchedule: InstagramTodayScheduleItem[] = [];
	let loading = true;
	let error: string | null = null;
	let refreshInterval: number;

	async function fetchData() {
		try {
			const [statsData, runsData, scheduleData] = await Promise.all([
				instagramApi.stats(),
				instagramApi.runs({ limit: 5 }),
				instagramApi.todaySchedule()
			]);
			stats = statsData;
			recentRuns = runsData;
			todaySchedule = scheduleData;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function formatTimeAgo(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			const now = new Date();
			const diffMs = now.getTime() - date.getTime();
			const diffSecs = Math.floor(diffMs / 1000);

			if (diffSecs < 0) return '-';
			if (diffSecs < 60) return `${diffSecs}초 전`;

			const diffMins = Math.floor(diffSecs / 60);
			if (diffMins < 60) return `${diffMins}분 전`;

			const diffHours = Math.floor(diffMins / 60);
			if (diffHours < 24) return `${diffHours}시간 전`;

			const diffDays = Math.floor(diffHours / 24);
			return `${diffDays}일 전`;
		} catch {
			return '-';
		}
	}

	function getScheduleStatusColor(status: string): string {
		switch (status) {
			case 'completed':
				return 'bg-green-100 text-green-800';
			case 'running':
				return 'bg-blue-100 text-blue-800';
			case 'pending':
				return 'bg-yellow-100 text-yellow-800';
			case 'missed':
				return 'bg-red-100 text-red-800';
			default:
				return 'bg-gray-100 text-gray-800';
		}
	}

	function getScheduleStatusLabel(status: string): string {
		switch (status) {
			case 'completed':
				return '완료';
			case 'running':
				return '실행 중';
			case 'pending':
				return '대기 중';
			case 'missed':
				return '놓침';
			default:
				return status;
		}
	}

	onMount(() => {
		fetchData();
		refreshInterval = setInterval(fetchData, 30000);
	});

	onDestroy(() => {
		if (refreshInterval) clearInterval(refreshInterval);
	});
</script>

<div class="p-6">
	<div class="mb-6 flex justify-between items-center">
		<div>
			<h1 class="text-2xl font-bold text-gray-900">Instagram</h1>
			<p class="text-gray-500 mt-1">Instagram 크롤링 대시보드 및 태그 관리</p>
		</div>
		{#if activeTab === 'dashboard'}
			<button onclick={fetchData} class="btn btn-secondary btn-sm flex items-center gap-2">
				새로고침
			</button>
		{/if}
	</div>

	<!-- 탭 네비게이션 -->
	<div class="border-b border-gray-200 mb-6">
		<nav class="flex space-x-8">
			<button
				class="py-2 px-1 border-b-2 font-medium text-sm {activeTab === 'dashboard' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
				onclick={() => activeTab = 'dashboard'}
			>
				대시보드
			</button>
			<button
				class="py-2 px-1 border-b-2 font-medium text-sm {activeTab === 'tags' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
				onclick={() => activeTab = 'tags'}
			>
				태그 관리
			</button>
		</nav>
	</div>

	{#if activeTab === 'dashboard'}
		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
				{error}
			</div>
		{:else}
			<!-- 워커 상태 및 통계 카드 -->
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
				<!-- 워커 상태 카드 -->
				<WorkerStatusCard />

				<!-- 통계 카드들 -->
				<div class="card text-center">
					<p class="text-3xl font-bold text-gray-900">{stats?.total_posts || 0}</p>
					<p class="text-sm text-gray-500">전체 게시물</p>
				</div>
				<div class="card text-center">
					<p class="text-3xl font-bold text-blue-600">{stats?.today_posts || 0}</p>
					<p class="text-sm text-gray-500">오늘 수집</p>
				</div>
				<div class="card text-center">
					<p class="text-3xl font-bold text-green-600">{stats?.success_runs || 0}</p>
					<p class="text-sm text-gray-500">성공 실행</p>
				</div>
				<div class="card text-center">
					<p class="text-3xl font-bold text-purple-600">{stats?.unique_accounts || 0}</p>
					<p class="text-sm text-gray-500">수집 계정</p>
				</div>
			</div>

			<!-- 실행 중인 크롤러 정보 -->
			{#if stats?.running_crawl}
				<div class="card mb-6 border-l-4 border-blue-500 bg-blue-50">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-4">
							<div class="flex items-center gap-2">
								<div class="w-3 h-3 bg-blue-500 rounded-full animate-pulse"></div>
								<h3 class="text-lg font-semibold text-blue-900">크롤링 실행 중</h3>
							</div>
							<div class="text-sm text-blue-700">
								<span class="font-medium">{stats.running_crawl.account_username || `계정 #${stats.running_crawl.service_account_id}`}</span>
								<span class="mx-2">|</span>
								<span>시작: {formatTimeAgo(stats.running_crawl.started_at)}</span>
							</div>
						</div>
						<div class="flex items-center gap-4">
							<div class="text-right">
								<p class="text-2xl font-bold text-blue-900">{stats.running_crawl.total_collected}</p>
								<p class="text-xs text-blue-600">수집</p>
							</div>
							<div class="text-right">
								<p class="text-2xl font-bold text-green-700">{stats.running_crawl.new_saved}</p>
								<p class="text-xs text-green-600">신규</p>
							</div>
						</div>
					</div>
				</div>
			{/if}

			<!-- 마지막 수집 정보 -->
			<div class="card mb-6">
				<div class="flex items-center justify-between">
					<div>
						<h3 class="text-lg font-semibold text-gray-900">마지막 수집</h3>
						<p class="text-sm text-gray-500">
							{stats?.last_run_at ? formatTimeAgo(stats.last_run_at) : '아직 수집 기록 없음'}
						</p>
					</div>
					<div class="flex gap-2">
						<a href="/instagram/posts" class="btn btn-primary btn-sm"> 게시물 보기 </a>
						<a href="/instagram/history" class="btn btn-secondary btn-sm"> 크롤링 이력 </a>
						<a href="/instagram/schedule" class="btn btn-secondary btn-sm"> 설정 </a>
					</div>
				</div>
			</div>

			<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
				<!-- 오늘 스케줄 -->
				<div class="card">
					<h3 class="text-lg font-semibold text-gray-900 mb-4">오늘 스케줄</h3>
					{#if todaySchedule.length === 0}
						<p class="text-gray-500 text-center py-4">스케줄 없음</p>
					{:else}
						<div class="space-y-2">
							{#each todaySchedule as item}
								<div
									class="flex items-center justify-between py-2 px-3 bg-gray-50 rounded-lg"
								>
									<span class="font-medium">{item.scheduled_time}</span>
									<span
										class="px-2 py-0.5 text-xs rounded-full {getScheduleStatusColor(item.status)}"
									>
										{getScheduleStatusLabel(item.status)}
									</span>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- 최근 실행 기록 -->
				<div class="card">
					<div class="flex items-center justify-between mb-4">
						<h3 class="text-lg font-semibold text-gray-900">최근 실행 기록</h3>
						<a href="/instagram/runs" class="text-sm text-blue-600 hover:text-blue-800">전체 보기</a>
					</div>
					{#if recentRuns.length === 0}
						<p class="text-gray-500 text-center py-4">실행 기록 없음</p>
					{:else}
						<div class="space-y-2">
							{#each recentRuns as run}
								<div
									class="flex items-center justify-between py-2 px-3 bg-gray-50 rounded-lg"
								>
									<div>
										<span class="text-sm font-medium">
											{formatDateTime(run.started_at)}
										</span>
										<span class="text-xs text-gray-500 ml-2">
											수집: {run.total_collected} / 신규: {run.new_saved}
										</span>
									</div>
									{#if !run.finished_at}
										<span class="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-800 animate-pulse">
											실행 중
										</span>
									{:else if run.success}
										<span class="px-2 py-0.5 text-xs rounded-full bg-green-100 text-green-800">
											성공
										</span>
									{:else}
										<span class="px-2 py-0.5 text-xs rounded-full bg-red-100 text-red-800">
											실패
										</span>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/if}
	{/if}

	{#if activeTab === 'tags'}
		<TagManager />
	{/if}
</div>
