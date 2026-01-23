<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { crawlApi } from '$lib/api';
	import type { CrawlSchedule, CrawlScheduleRun, CrawlRunStats, RunPost } from '$lib/types';

	let schedule: CrawlSchedule | null = null;
	let runs: CrawlScheduleRun[] = [];
	let stats: CrawlRunStats | null = null;
	let loading = true;
	let error: string | null = null;

	// 페이지네이션
	let currentPage = 1;
	let limit = 20;
	let total = 0;

	// 필터
	let status: string = '';

	// 포스트 모달
	let showPostsModal = false;
	let selectedRun: CrawlScheduleRun | null = null;
	let runPosts: RunPost[] = [];
	let loadingPosts = false;
	let postsPage = 1;
	let postsLimit = 50;
	let postsTotal = 0;

	$: scheduleId = parseInt($page.params.id);
	$: totalPages = Math.ceil(total / limit);
	$: postsTotalPages = Math.ceil(postsTotal / postsLimit);

	async function fetchSchedule() {
		try {
			schedule = await crawlApi.getSchedule(scheduleId);
		} catch (e) {
			console.error('Schedule fetch error:', e);
		}
	}

	async function fetchRuns() {
		try {
			loading = true;
			const response = await crawlApi.getScheduleRuns(scheduleId, {
				page: currentPage,
				limit,
				status: status || undefined
			});
			runs = response.items ?? [];
			total = response.total ?? 0;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function fetchStats() {
		try {
			stats = await crawlApi.getScheduleStats(scheduleId, 7);
		} catch (e) {
			console.error('Stats fetch error:', e);
		}
	}

	function handleFilterChange() {
		currentPage = 1;
		fetchRuns();
	}

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				year: 'numeric',
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function formatDuration(seconds: number | null): string {
		if (seconds === null || seconds === undefined) return '-';
		if (seconds < 60) return `${seconds}초`;
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}분 ${secs}초`;
	}

	function getStatusBadge(status: string): { class: string; text: string } {
		switch (status) {
			case 'running':
				return { class: 'bg-primary-light text-primary', text: '실행중' };
			case 'completed':
				return { class: 'bg-success-light text-success', text: '완료' };
			case 'failed':
				return { class: 'bg-error-light text-error', text: '실패' };
			default:
				return { class: 'bg-muted text-foreground', text: status };
		}
	}

	function getStopReasonLabel(reason: string | null): string {
		if (!reason) return '-';
		switch (reason) {
			case 'max_posts_reached': return '최대 수집';
			case 'duplicate_stop': return '중복 종료';
			case 'error': return '오류';
			case 'manual': return '수동 종료';
			case 'search_queued': return '검색 요청됨 (비동기)';
			case 'search_completed': return '검색 완료';
			default: return reason;
		}
	}

	async function openPostsModal(run: CrawlScheduleRun) {
		selectedRun = run;
		showPostsModal = true;
		postsPage = 1;
		await fetchRunPosts();
	}

	async function fetchRunPosts() {
		if (!selectedRun) return;

		try {
			loadingPosts = true;
			const response = await crawlApi.getRunPosts(scheduleId, selectedRun.id, {
				page: postsPage,
				limit: postsLimit
			});
			runPosts = response.items ?? [];
			postsTotal = response.total ?? 0;
		} catch (e) {
			console.error('Posts fetch error:', e);
		} finally {
			loadingPosts = false;
		}
	}

	function closePostsModal() {
		showPostsModal = false;
		selectedRun = null;
		runPosts = [];
	}

	onMount(() => {
		fetchSchedule();
		fetchRuns();
		fetchStats();
	});
</script>

<div class="p-6 max-w-7xl mx-auto">
	<div class="mb-6 flex justify-between items-center">
		<div>
			<h2 class="text-2xl font-bold text-foreground">
				{#if schedule}
					{schedule.display_name || schedule.name}
				{:else}
					스케줄 #{scheduleId}
				{/if}
				실행 이력
			</h2>
			<p class="text-sm text-muted-foreground mt-1">스케줄 실행 기록</p>
		</div>
		<a href="/crawl/schedules" class="btn btn-secondary btn-sm">스케줄 목록</a>
	</div>

	<!-- 통계 요약 -->
	{#if stats}
		<div class="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
			<div class="card text-center">
				<p class="text-2xl font-bold text-foreground">{stats.total_runs}</p>
				<p class="text-sm text-muted-foreground">전체 실행</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-success">{stats.completed_runs}</p>
				<p class="text-sm text-muted-foreground">완료</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-error">{stats.failed_runs}</p>
				<p class="text-sm text-muted-foreground">실패</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-primary">{stats.success_rate.toFixed(1)}%</p>
				<p class="text-sm text-muted-foreground">성공률</p>
			</div>
			<div class="card text-center">
				<p class="text-2xl font-bold text-purple">{stats.total_saved}</p>
				<p class="text-sm text-muted-foreground">총 저장</p>
			</div>
		</div>
	{/if}

	<!-- 필터 -->
	<div class="card mb-6">
		<div class="flex flex-wrap gap-4 items-center">
			<div>
				<label for="status" class="block text-sm font-medium text-foreground mb-1">상태</label>
				<select
					id="status"
					bind:value={status}
					onchange={handleFilterChange}
					class="input input-sm w-32"
				>
					<option value="">전체</option>
					<option value="running">실행중</option>
					<option value="completed">완료</option>
					<option value="failed">실패</option>
				</select>
			</div>
		</div>
	</div>

	<!-- 실행 목록 -->
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if !runs || runs.length === 0}
		<div class="card text-center py-12">
			<p class="text-muted-foreground">실행 기록이 없습니다</p>
		</div>
	{:else}
		<div class="card overflow-hidden">
			<table class="min-w-full divide-y divide-border">
				<thead class="bg-background">
					<tr>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">시작 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">상태</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">수집</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">신규</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">업데이트</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">중복</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">종료 사유</th>
						<th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">소요 시간</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">워커</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-border">
					{#each runs as run}
						{@const badge = getStatusBadge(run.status)}
						<tr class="hover:bg-muted cursor-pointer" onclick={() => openPostsModal(run)}>
							<td class="px-4 py-3 text-sm text-foreground">
								{formatDateTime(run.started_at)}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {badge.class}">
									{badge.text}
								</span>
								{#if run.error_message}
									<span class="ml-2 text-xs text-error" title={run.error_message}>
										{run.error_message.substring(0, 25)}...
									</span>
								{/if}
							</td>
							<td class="px-4 py-3 text-sm text-foreground text-right">
								{run.collected_count}
							</td>
							<td class="px-4 py-3 text-sm text-success text-right font-medium">
								{run.created_count}
							</td>
							<td class="px-4 py-3 text-sm text-blue-600 text-right font-medium">
								{run.updated_count}
							</td>
							<td class="px-4 py-3 text-sm text-gray-500 text-right">
								{run.unchanged_count}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">
								{getStopReasonLabel(run.stop_reason)}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground text-right">
								{formatDuration(run.duration_seconds)}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">
								{run.worker_id || '-'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- 페이지네이션 -->
		{#if totalPages > 1}
			<div class="flex justify-center items-center gap-2 mt-6">
				<button
					onclick={() => { currentPage = Math.max(1, currentPage - 1); fetchRuns(); }}
					disabled={currentPage === 1}
					class="btn btn-secondary btn-sm"
				>
					이전
				</button>
				<span class="text-sm text-muted-foreground">
					{currentPage} / {totalPages}
				</span>
				<button
					onclick={() => { currentPage = Math.min(totalPages, currentPage + 1); fetchRuns(); }}
					disabled={currentPage === totalPages}
					class="btn btn-secondary btn-sm"
				>
					다음
				</button>
			</div>
		{/if}
	{/if}
</div>

<!-- 포스트 목록 모달 -->
{#if showPostsModal && selectedRun}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-6xl w-full max-h-[90vh] overflow-hidden">
			<!-- 모달 헤더 -->
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<div>
					<h2 class="text-xl font-bold text-foreground">
						수집된 포스트 목록 (Run #{selectedRun.id})
					</h2>
					<p class="text-sm text-muted-foreground mt-1">
						{formatDateTime(selectedRun.started_at)} - 총 {selectedRun.collected_count}개 수집, {selectedRun.saved_count}개 저장
					</p>
				</div>
				<button
					onclick={closePostsModal}
					class="text-muted-foreground hover:text-muted-foreground text-2xl leading-none"
				>
					&times;
				</button>
			</div>

			<!-- 모달 컨텐츠 -->
			<div class="p-6 overflow-y-auto max-h-[calc(90vh-160px)]">
				{#if loadingPosts}
					<div class="flex justify-center items-center h-64">
						<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
					</div>
				{:else if runPosts.length === 0}
					<div class="text-center py-12">
						<p class="text-muted-foreground">수집된 포스트가 없습니다</p>
					</div>
				{:else}
					<div class="space-y-3">
						{#each runPosts as post}
							<div class="border border-border rounded-lg p-4 hover:bg-muted transition-colors">
								<div class="flex items-start justify-between gap-4">
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2 mb-2">
											<span class="font-medium text-foreground">@{post.account}</span>
											{#if post.status === 'created'}
												<span class="px-2 py-0.5 text-xs rounded-full bg-success-light text-success font-medium">
													신규 추가
												</span>
											{:else if post.status === 'updated'}
												<span class="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700 font-medium">
													업데이트됨
												</span>
											{:else}
												<span class="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">
													중복 (변경없음)
												</span>
											{/if}
											{#if post.has_duplicate_post_id}
												<span class="px-2 py-0.5 text-xs rounded-full bg-error-light text-error">
													중복 ID
												</span>
											{/if}
										</div>
										<p class="text-sm text-muted-foreground truncate mb-1">
											{post.caption || '(캡션 없음)'}
										</p>
										{#if post.url}
											<a
												href={post.url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-xs text-primary hover:underline"
											>
												{post.url}
											</a>
										{/if}
									</div>
									<div class="text-right text-xs text-muted-foreground whitespace-nowrap">
										<div>{formatDateTime(post.collected_at)}</div>
										<div class="text-xs text-muted-foreground mt-1">ID: {post.post_id}</div>
									</div>
								</div>
							</div>
						{/each}
					</div>

					<!-- 페이지네이션 -->
					{#if postsTotalPages > 1}
						<div class="flex justify-center items-center gap-2 mt-6">
							<button
								onclick={() => { postsPage = Math.max(1, postsPage - 1); fetchRunPosts(); }}
								disabled={postsPage === 1}
								class="btn btn-secondary btn-sm"
							>
								이전
							</button>
							<span class="text-sm text-muted-foreground">
								{postsPage} / {postsTotalPages}
							</span>
							<button
								onclick={() => { postsPage = Math.min(postsTotalPages, postsPage + 1); fetchRunPosts(); }}
								disabled={postsPage === postsTotalPages}
								class="btn btn-secondary btn-sm"
							>
								다음
							</button>
						</div>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/if}
