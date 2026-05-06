<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui';
	import { isAdmin } from '$lib/stores/auth';
  import { fetchWithTimeout } from '$lib/api/client';
	import MarkdownContent from '$lib/components/markdown/MarkdownContent.svelte';
	import { toast } from '$lib/stores/toast';
	import { confirm } from '$lib/stores/confirm';

	type Report = {
		id: number;
		report_type: string;
		period_start: string;
		period_end: string;
		title: string | null;
		content: string;
		summary: string | null;
		statistics: string | null;
		llm_request_id: number | null;
		schedule_run_id: number | null;
		generated_at: string;
		format: string;
	};

	let reportId: string = $derived($page.params.id ?? '');
	let report: Report | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);
	let deleting = $state(false);

	function errorMessage(err: unknown): string {
		return err instanceof Error ? err.message : '삭제 중 오류가 발생했습니다.';
	}

	const reportTypeNames: Record<string, string> = {
		nightly_cleanup: 'WTools 아카이빙 보고서',
		sleep_now: '수면 시스템 야간 실행 보고서',
		daily_summary: '일일 요약 보고서'
	};

	async function loadReport() {
		loading = true;
		error = null;

		try {
			const response = await fetchWithTimeout(`/api/v1/reports/${reportId}`);

			if (!response.ok) {
				if (response.status === 404) {
					throw new Error('보고서를 찾을 수 없습니다.');
				}
				throw new Error(`Failed to load report: ${response.statusText}`);
			}

			report = await response.json();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Unknown error';
		} finally {
			loading = false;
		}
	}

	async function deleteReport() {
		const confirmed = await confirm({
			title: '보고서 삭제',
			message: '정말 이 보고서를 삭제하시겠습니까?',
			confirmText: '삭제',
			variant: 'danger'
		});
		if (!confirmed) {
			return;
		}

		deleting = true;

		try {
			const response = await fetchWithTimeout(`/api/v1/reports/${reportId}`, {
				method: 'DELETE',
				credentials: 'include'
			});

			if (!response.ok) {
				throw new Error('보고서 삭제에 실패했습니다.');
			}

			goto('/reports');
		} catch (err: unknown) {
			toast.error(errorMessage(err));
		} finally {
			deleting = false;
		}
	}

	function formatDate(dateStr: string): string {
		const date = new Date(dateStr);
		return date.toLocaleString('ko-KR', {
			year: 'numeric',
			month: '2-digit',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
		});
	}

	function formatPeriod(start: string, end: string): string {
		const startDate = new Date(start);
		const endDate = new Date(end);

		return `${startDate.toLocaleDateString('ko-KR')} ~ ${endDate.toLocaleDateString('ko-KR')}`;
	}

	onMount(() => {
		loadReport();
	});
</script>

<svelte:head>
	<title>{report?.title || '보고서'} - Monitor Page</title>
</svelte:head>

<div class="container mx-auto p-6 max-w-4xl">
	<!-- 헤더 -->
	<div class="mb-6 flex items-center justify-between">
		<Button onclick={() => goto('/reports')} variant="outline">
			← 목록으로
		</Button>

		{#if $isAdmin && report}
			<Button onclick={deleteReport} disabled={deleting} variant="destructive">
				{deleting ? '삭제 중...' : '삭제'}
			</Button>
		{/if}
	</div>

	<!-- 로딩/에러 상태 -->
	{#if loading}
		<div class="text-center py-12">
			<div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-neutral-300 border-t-brand-500"></div>
			<p class="mt-2 text-neutral-600 dark:text-neutral-400">보고서를 불러오는 중...</p>
		</div>
	{:else if error}
		<div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
			<p class="text-red-800 dark:text-red-200">{error}</p>
		</div>
	{:else if report}
		<!-- 보고서 상세 -->
		<div class="bg-white dark:bg-neutral-800 rounded-lg shadow-sm">
			<!-- 헤더 -->
			<div class="border-b border-neutral-200 dark:border-neutral-700 p-6">
				<div class="flex items-start justify-between">
					<div>
						<div class="flex items-center gap-2 mb-2">
							<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-brand-100 text-brand-800 dark:bg-brand-900/30 dark:text-brand-300">
								{reportTypeNames[report.report_type] || report.report_type}
							</span>
						</div>
						<h2 class="text-2xl font-bold text-neutral-800 dark:text-neutral-100">
							{report.title || '제목 없음'}
						</h2>
						{#if report.summary}
							<p class="text-sm text-neutral-600 dark:text-neutral-400 mt-2">
								{report.summary}
							</p>
						{/if}
					</div>
				</div>

				<!-- 메타 정보 -->
				<div class="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
					<div>
						<span class="text-neutral-500 dark:text-neutral-400">분석 기간:</span>
						<span class="ml-2 text-neutral-700 dark:text-neutral-300">
							{formatPeriod(report.period_start, report.period_end)}
						</span>
					</div>
					<div>
						<span class="text-neutral-500 dark:text-neutral-400">생성 일시:</span>
						<span class="ml-2 text-neutral-700 dark:text-neutral-300">
							{formatDate(report.generated_at)}
						</span>
					</div>
					<div>
						<span class="text-neutral-500 dark:text-neutral-400">형식:</span>
						<span class="ml-2 text-neutral-700 dark:text-neutral-300">
							{report.format}
						</span>
					</div>
				</div>
			</div>

			<!-- 본문 -->
			<div class="p-6">
				{#if report.format === 'markdown'}
					<MarkdownContent content={report.content} variant="document" />
				{:else}
					<pre class="whitespace-pre-wrap font-sans text-sm text-neutral-700 dark:text-neutral-300 bg-neutral-50 dark:bg-neutral-900 rounded-lg p-4 overflow-x-auto">{report.content}</pre>
				{/if}
			</div>

			<!-- 통계 (있는 경우) -->
			{#if report.statistics}
				<div class="border-t border-neutral-200 dark:border-neutral-700 p-6">
					<h2 class="text-lg font-semibold text-neutral-800 dark:text-neutral-100 mb-3">통계</h2>
					<pre class="text-sm text-neutral-600 dark:text-neutral-400 bg-neutral-50 dark:bg-neutral-900 rounded-lg p-4 overflow-x-auto">{report.statistics}</pre>
				</div>
			{/if}

			<!-- 관련 정보 -->
			{#if report.llm_request_id || report.schedule_run_id}
				<div class="border-t border-neutral-200 dark:border-neutral-700 p-6 bg-neutral-50 dark:bg-neutral-900/50">
					<h3 class="text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">관련 정보</h3>
					<div class="text-xs text-neutral-500 dark:text-neutral-400 space-y-1">
						{#if report.llm_request_id}
							<div>LLM Request ID: {report.llm_request_id}</div>
						{/if}
						{#if report.schedule_run_id}
							<div>Schedule Run ID: {report.schedule_run_id}</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
