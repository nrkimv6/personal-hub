<script lang="ts">
	import { onMount } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import { testRunsApi, type TestRunItem, type TestResultItem } from '$lib/api';

	let runs: TestRunItem[] = [];
	let loading = true;
	let error: string | null = null;
	let successMessage: string | null = null;

	// 필터
	let filterStatus = '';

	// 확장된 run IDs (상세 결과 표시)
	let expandedRunIds = new Set<number>();

	// 수동 트리거 모달
	let showTriggerModal = false;
	let triggerPath = 'tests/';
	let triggerArgs = '';
	let triggerAutoFix = true;
	let triggering = false;

	// 로그 모달
	let showLogModal = false;
	let logContent = '';
	let logRunId: number | null = null;
	let logLoading = false;

	async function fetchRuns() {
		loading = true;
		error = null;
		try {
			runs = await testRunsApi.list({ status: filterStatus || undefined, limit: 50 });
		} catch (e) {
			error = e instanceof Error ? e.message : '불러오기 실패';
		} finally {
			loading = false;
		}
	}

	function toggleExpand(runId: number) {
		if (expandedRunIds.has(runId)) {
			expandedRunIds.delete(runId);
		} else {
			expandedRunIds.add(runId);
		}
		expandedRunIds = new Set(expandedRunIds); // reactivity
	}

	async function triggerRun() {
		triggering = true;
		error = null;
		try {
			const extraArgsList = triggerArgs
				.split(/\s+/)
				.map((s) => s.trim())
				.filter(Boolean);
			const resp = await testRunsApi.trigger(triggerPath.trim() || 'tests/', extraArgsList, triggerAutoFix);
			successMessage = `테스트 실행 시작됨 (run_id: ${resp.test_run_id})`;
			showTriggerModal = false;
			setTimeout(() => fetchRuns(), 1000);
		} catch (e) {
			error = e instanceof Error ? e.message : '실행 실패';
		} finally {
			triggering = false;
		}
	}

	async function showLog(run: TestRunItem) {
		logRunId = run.id;
		showLogModal = true;
		logLoading = true;
		logContent = '';
		try {
			const resp = await testRunsApi.getLog(run.id);
			logContent = resp.content;
		} catch (e) {
			logContent = e instanceof Error ? `로그 로드 실패: ${e.message}` : '로그 로드 실패';
		} finally {
			logLoading = false;
		}
	}

	function formatDateTime(iso: string | null): string {
		if (!iso) return '-';
		try {
			return new Date(iso).toLocaleString('ko-KR', {
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function formatDuration(sec: number | null): string {
		if (sec === null || sec === undefined) return '-';
		if (sec < 60) return `${sec.toFixed(1)}s`;
		const m = Math.floor(sec / 60);
		const s = Math.floor(sec % 60);
		return `${m}m ${s}s`;
	}

	function statusBadge(status: string): string {
		switch (status) {
			case 'completed': return 'bg-green-100 text-green-800';
			case 'running':   return 'bg-blue-100 text-blue-800';
			case 'failed':    return 'bg-red-100 text-red-800';
			case 'passed':    return 'bg-green-100 text-green-800';
			case 'error':     return 'bg-orange-100 text-orange-800';
			case 'skipped':   return 'bg-gray-100 text-gray-600';
			default:          return 'bg-gray-100 text-gray-600';
		}
	}

	function statusText(status: string): string {
		switch (status) {
			case 'completed': return '완료';
			case 'running':   return '실행 중';
			case 'failed':    return '실패';
			case 'passed':    return 'PASS';
			case 'error':     return 'ERROR';
			case 'skipped':   return 'SKIP';
			default:          return status;
		}
	}

	onMount(() => fetchRuns());
</script>

<div>
	<PageHeader title="테스트 실행 이력" subtitle="pytest 자동 실행 결과를 확인합니다">
		<div class="flex items-center gap-2">
			<select
				bind:value={filterStatus}
				onchange={fetchRuns}
				class="px-3 py-1.5 border rounded-lg text-sm focus:ring-2 focus:ring-ring"
			>
				<option value="">전체 상태</option>
				<option value="running">실행 중</option>
				<option value="completed">완료</option>
				<option value="failed">실패</option>
			</select>
			<button onclick={fetchRuns} class="btn btn-secondary btn-sm">새로고침</button>
			<button onclick={() => (showTriggerModal = true)} class="btn btn-primary btn-sm">
				🧪 수동 실행
			</button>
		</div>
	</PageHeader>

	{#if successMessage}
		<div class="bg-green-50 border border-green-200 text-green-800 px-4 py-3 rounded-lg mb-4">
			{successMessage}
		</div>
	{/if}
	{#if error}
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
			{error}
		</div>
	{/if}

	{#if loading}
		<div class="flex justify-center items-center h-48">
			<div class="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600"></div>
		</div>
	{:else if runs.length === 0}
		<div class="card text-center py-12">
			<p class="text-2xl mb-2">🧪</p>
			<p class="text-muted-foreground">실행 이력이 없습니다</p>
			<p class="text-sm text-muted-foreground mt-1">스케줄을 등록하거나 수동 실행하세요</p>
		</div>
	{:else}
		<div class="space-y-3">
			{#each runs as run}
				{@const expanded = expandedRunIds.has(run.id)}
				<div class="card">
					<!-- 실행 요약 행 -->
					<button
						class="w-full flex items-center justify-between text-left"
						onclick={() => toggleExpand(run.id)}
					>
						<div class="flex items-center gap-3">
							<span class="text-lg">{expanded ? '▼' : '▶'}</span>
							<div>
								<div class="flex items-center gap-2">
									<span class="font-medium text-foreground text-sm">{run.test_path}</span>
									<span class="px-2 py-0.5 text-xs rounded-full {statusBadge(run.status)}">
										{statusText(run.status)}
									</span>
									{#if run.triggered_by === 'manual'}
										<span class="px-1.5 py-0.5 text-xs rounded bg-gray-100 text-gray-600">수동</span>
									{:else if run.triggered_by === 'scheduler'}
										<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 text-blue-600">스케줄</span>
									{/if}
								</div>
								<div class="text-xs text-muted-foreground mt-0.5 flex gap-3">
									<span>{formatDateTime(run.started_at)}</span>
									<span>소요: {formatDuration(run.duration_seconds)}</span>
								</div>
							</div>
						</div>

						<!-- 통계 -->
						<div class="flex items-center gap-3 text-sm">
							<span class="text-green-700 font-medium">✓ {run.passed}</span>
							{#if run.failed > 0}
								<span class="text-red-700 font-medium">✗ {run.failed}</span>
							{/if}
							{#if run.errors > 0}
								<span class="text-orange-700 font-medium">! {run.errors}</span>
							{/if}
							{#if run.skipped > 0}
								<span class="text-gray-500">⊘ {run.skipped}</span>
							{/if}
							<span class="text-muted-foreground">/ {run.total_tests}</span>
							<button
								onclick={(e) => { e.stopPropagation(); showLog(run); }}
								class="btn btn-sm text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded ml-1"
							>
								로그
							</button>
						</div>
					</button>

					<!-- 펼쳐진 결과 목록 -->
					{#if expanded && run.results.length > 0}
						<div class="mt-4 border-t border-border pt-4 space-y-2">
							{#each run.results as result}
								<div class="flex items-start gap-3 py-2 px-3 rounded-lg hover:bg-gray-50">
									<span class="px-2 py-0.5 text-xs rounded-full {statusBadge(result.status)} shrink-0 mt-0.5">
										{statusText(result.status)}
									</span>
									<div class="flex-1 min-w-0">
										<p class="text-sm font-mono truncate text-foreground" title={result.test_name}>
											{result.test_name}
										</p>
										{#if result.error_message}
											<p class="text-xs text-red-600 mt-0.5 truncate">{result.error_message}</p>
										{/if}
										{#if result.fix_plan}
											<details class="mt-1">
												<summary class="text-xs text-primary cursor-pointer">🤖 수정계획 보기</summary>
												<div class="mt-2 p-3 bg-blue-50 rounded text-xs font-mono whitespace-pre-wrap break-words text-foreground">
													{result.fix_plan}
												</div>
											</details>
										{/if}
									</div>
									<span class="text-xs text-muted-foreground shrink-0">
										{formatDuration(result.duration_seconds)}
									</span>
								</div>
							{/each}
						</div>
					{:else if expanded && run.results.length === 0}
						<div class="mt-4 border-t border-border pt-4 text-sm text-muted-foreground text-center py-4">
							결과가 없습니다
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- 수동 실행 모달 -->
{#if showTriggerModal}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-md w-full">
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<h2 class="text-lg font-bold text-foreground">🧪 테스트 수동 실행</h2>
				<button onclick={() => (showTriggerModal = false)} class="text-muted-foreground text-2xl leading-none">&times;</button>
			</div>
			<div class="p-6 space-y-4">
				<div>
					<label for="trigger-path" class="block text-sm font-medium text-foreground mb-1">테스트 경로</label>
					<input
						id="trigger-path"
						type="text"
						bind:value={triggerPath}
						class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring font-mono text-sm"
					/>
				</div>
				<div>
					<label for="trigger-args" class="block text-sm font-medium text-foreground mb-1">추가 인자</label>
					<input
						id="trigger-args"
						type="text"
						bind:value={triggerArgs}
						placeholder="예: -k test_api"
						class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring font-mono text-sm"
					/>
				</div>
				<div class="flex items-center gap-3">
					<button
						onclick={() => (triggerAutoFix = !triggerAutoFix)}
						class="relative inline-flex items-center h-6 rounded-full w-11 transition-colors {triggerAutoFix ? 'bg-primary' : 'bg-secondary'}"
					>
						<span class="inline-block w-4 h-4 transform bg-white rounded-full transition-transform {triggerAutoFix ? 'translate-x-6' : 'translate-x-1'}"></span>
					</button>
					<span class="text-sm text-foreground">실패 시 LLM 수정계획 자동 생성</span>
				</div>
			</div>
			<div class="px-6 py-4 border-t border-border flex justify-end gap-2">
				<button onclick={() => (showTriggerModal = false)} class="btn btn-secondary">취소</button>
				<button onclick={triggerRun} disabled={triggering} class="btn btn-primary">
					{#if triggering}실행 중...{:else}실행{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- 로그 모달 -->
{#if showLogModal}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-3xl w-full max-h-[85vh] flex flex-col">
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<h2 class="text-lg font-bold text-foreground">실행 로그 (run #{logRunId})</h2>
				<button onclick={() => (showLogModal = false)} class="text-muted-foreground text-2xl leading-none">&times;</button>
			</div>
			<div class="flex-1 overflow-auto p-6">
				{#if logLoading}
					<div class="flex justify-center py-8">
						<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
					</div>
				{:else}
					<pre class="text-xs font-mono whitespace-pre-wrap break-words text-foreground bg-gray-50 p-4 rounded">{logContent || '(로그 없음)'}</pre>
				{/if}
			</div>
		</div>
	</div>
{/if}
