<script lang="ts">
	import { Button } from '$lib/components/ui';

	import { onMount } from 'svelte';
	import { llmApi, type LLMRequest, type LLMStats, type LLMWorkerStatus, type LLMHistoryStats, type LLMQueueStats, type LLMCallerGroup, type LLMGroupedListResponse, type QuotaStatusMap, type ProviderInfo } from '$lib/api';
	import LLMPerformance from '$lib/components/LLMPerformance.svelte';
	import ClaudeSessionsTab from './ClaudeSessionsTab.svelte';
	import { toast } from '$lib/stores/toast';
	import { fetchQuotaStatus, getQuotaWarning } from '$lib/stores/quotaStore';

	// 상태
	let requests: LLMRequest[] = [];
	let stats: LLMStats | null = null;
	let workerStatus: LLMWorkerStatus | null = null;
	let historyStats: LLMHistoryStats | null = null;
	let queueStats: LLMQueueStats | null = null;

	// 그룹 뷰 상태
	let callerGroups: LLMCallerGroup[] = [];
	let groupedResponse: LLMGroupedListResponse | null = null;
	let viewMode: 'individual' | 'grouped' = 'individual';
	let onlyWithoutSuccess = false;

	let loading = true;
	let error = $state<string | null>(null);

	// 페이지네이션
	let currentPage = 1;
	let pageSize = 20;
	let total = 0;
	let pages = 0;

	// 그룹 뷰 페이지네이션
	let groupCurrentPage = 1;
	let groupPageSize = 50;
	let groupTotal = 0;
	let groupPages = 0;

	// 그룹 선택 (multi-재요청용)
	let selectedGroupKeys: string[] = [];  // "caller_type:caller_id" 형식
	let groupSelectAll = false;

	// 필터 (탭에 따라 다르게 설정)
	let filterCallerType = '';
	let filterRequestedBy = '';
	let filterQueueName = '';  // '' = 전체, 'utility', 'system'

	// 선택
	let selectedIds: number[] = [];
	let selectAll = false;

	// 탭: queue(대기열), history(이력), create(수동생성), performance(성능), claude-sessions(세션 뷰어)
	type Tab = 'queue' | 'history' | 'create' | 'performance' | 'claude-sessions';
	let activeTab: Tab = 'queue';

	// 모달
	let selectedRequest: LLMRequest | null = null;
	let showModal = false;
	let editCwd = $state('');
	let editCwdSaving = $state(false);
	let quotaStatus: QuotaStatusMap = {};
	let countdownSeconds: number = 0;
	let countdownTimer: ReturnType<typeof setInterval> | null = null;

	// 수동 요청 생성 폼
	let createForm = $state({
		caller_type: 'test',
		caller_id: '',
		prompt: '',
		queue_name: 'utility',
		requested_by: 'manual',
		request_source: 'manual_test',
		provider: 'claude',
		model: '',
		cli_options: null as Record<string, unknown> | null,
		userInput: ''
	});
	let createLoading = false;
	let createError = $state<string | null>(null);
	let createSuccess = false;

	// Provider 목록 (API에서 동적 로드)
	let providers = $state<ProviderInfo[]>([]);
	let providersLoading = $state(true);
	let providersError = $state<string | null>(null);

	// Provider별 모델 목록 (API 로드 전 fallback)
	function getProviderModels(providerKey: string): string[] {
		const p = providers.find(x => x.key === providerKey);
		if (p && p.models.length > 0) return ['(기본)', ...p.models];
		return ['(기본)'];
	}

	// 프리셋 타입 정의
	interface Preset {
		label: string;
		caller_type?: string;
		caller_id_prefix?: string;
		queue_name?: string;
		provider?: string;
		model?: string;
		cliOptions?: Record<string, unknown>;
		promptPrefix?: string;
		userPromptPlaceholder?: string;
	}

	const presets: Preset[] = [
		{ label: '(직접 입력)' },
		{
			label: '계획서 작성',
			caller_type: 'test',
			caller_id_prefix: 'plan',
			queue_name: 'system',
			provider: 'claude',
			model: 'opus',
			cliOptions: { cwd: 'D:/work/project/tools/monitor-page', parse_json: false, allowed_tools: ['Read', 'Edit', 'Write', 'Glob', 'Grep'] },
			promptPrefix: '/plan ',
			userPromptPlaceholder: '아이디어나 요구사항을 입력하세요...'
		}
	];

	let selectedPreset: Preset = presets[0];
	let userInput = '';

	function applyPreset(preset: Preset) {
		selectedPreset = preset;
		if (preset.caller_id_prefix) {
			const now = new Date();
			const pad = (n: number) => String(n).padStart(2, '0');
			const dateStr = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
			createForm.caller_id = `${preset.caller_id_prefix}-${dateStr}`;
		} else {
			createForm.caller_id = '';
		}
		if (preset.queue_name) createForm.queue_name = preset.queue_name;
		if (preset.provider) createForm.provider = preset.provider;
		if (preset.model) createForm.model = preset.model;
		if (preset.caller_type) createForm.caller_type = preset.caller_type;
		createForm.cli_options = preset.cliOptions ?? null;
		// 프리셋 변경 시 사용자 입력은 보존 (이미 작성한 텍스트 유실 방지)
		// 직접 입력 ↔ 프리셋 전환 시에만 prompt 초기화
		if (preset.label === '(직접 입력)') {
			createForm.prompt = '';
		}
	}

	// Provider 변경 시 model 초기화
	$effect(() => {
		if (createForm.provider) {
			createForm.model = '';
		}
	});

	// 탭별 status 필터
	function getStatusFilter(): string | undefined {
		if (activeTab === 'queue') {
			return 'pending,processing';
		} else if (activeTab === 'history') {
			return 'completed,failed,cancelled';
		}
		return undefined;
	}

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const [listRes, statsRes, workerRes, queueStatsRes] = await Promise.all([
				llmApi.list({
					status: getStatusFilter(),
					caller_type: filterCallerType || undefined,
					requested_by: filterRequestedBy || undefined,
					queue_name: filterQueueName || undefined,
					page: currentPage,
					page_size: pageSize
				}),
				llmApi.getStats(),
				llmApi.getWorkerStatus(),
				llmApi.getQueueStats()
			]);

			// 서버에서 이미 status 필터링된 결과 사용
			requests = listRes.items;
			total = listRes.total;
			pages = listRes.pages || 1;
			stats = statsRes;
			workerStatus = workerRes;
			queueStats = queueStatsRes;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function fetchHistoryStats() {
		try {
			historyStats = await llmApi.getHistoryStats();
		} catch (e) {
			console.error('이력 통계 로드 실패:', e);
		}
	}

	async function fetchGroupedData() {
		loading = true;
		error = null;
		try {
			const [res, statsRes, workerRes] = await Promise.all([
				llmApi.listGroupedByCaller({
					caller_type: filterCallerType || undefined,
					only_without_success: onlyWithoutSuccess,
					page: groupCurrentPage,
					page_size: groupPageSize
				}),
				llmApi.getStats(),
				llmApi.getWorkerStatus()
			]);

			callerGroups = res.items;
			groupedResponse = res;
			groupTotal = res.total;
			groupPages = res.pages;
			stats = statsRes;
			workerStatus = workerRes;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function retryAllFailedWithoutSuccess() {
		if (!confirm(`성공한 적 없는 모든 caller의 실패 요청을 재시도하시겠습니까?`)) return;
		try {
			const result = await llmApi.retryFailedCallersWithoutSuccess(filterCallerType || undefined);
			alert(`재시도 완료: ${result.retried}개 요청 (${result.callers}개 caller)`);
			await fetchGroupedData();
		} catch (e) {
			alert('재시도 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// 그룹 선택 관련 함수
	function getGroupKey(group: LLMCallerGroup): string {
		return `${group.caller_type}:${group.caller_id}`;
	}

	function toggleGroupSelectAll() {
		groupSelectAll = !groupSelectAll;
		if (groupSelectAll) {
			selectedGroupKeys = callerGroups.map(g => getGroupKey(g));
		} else {
			selectedGroupKeys = [];
		}
	}

	function toggleGroupSelect(group: LLMCallerGroup) {
		const key = getGroupKey(group);
		if (selectedGroupKeys.includes(key)) {
			selectedGroupKeys = selectedGroupKeys.filter(k => k !== key);
		} else {
			selectedGroupKeys = [...selectedGroupKeys, key];
		}
	}

	async function multiRetrySelectedGroups() {
		if (selectedGroupKeys.length === 0) return;

		// 선택된 그룹들의 실패한 요청 ID들 수집
		const selectedGroups = callerGroups.filter(g => selectedGroupKeys.includes(getGroupKey(g)));
		const failedRequestIds: number[] = [];
		for (const group of selectedGroups) {
			failedRequestIds.push(...group.request_ids);
		}

		if (failedRequestIds.length === 0) {
			alert('선택된 그룹에 재시도할 실패 요청이 없습니다.');
			return;
		}

		if (!confirm(`선택된 ${selectedGroups.length}개 그룹의 ${failedRequestIds.length}개 실패 요청을 재시도하시겠습니까?`)) return;

		try {
			const result = await llmApi.batchRetry(failedRequestIds);
			alert(`재시도 완료: 성공 ${result.success}개, 스킵 ${result.skipped}개`);
			selectedGroupKeys = [];
			groupSelectAll = false;
			await fetchGroupedData();
		} catch (e) {
			alert('일괄 재시도 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	function truncatePrompt(prompt: string, maxLength: number = 80): string {
		if (!prompt) return '-';
		if (prompt.length <= maxLength) return prompt;
		return prompt.substring(0, maxLength) + '...';
	}

	function toggleViewMode() {
		viewMode = viewMode === 'individual' ? 'grouped' : 'individual';
		if (viewMode === 'grouped') {
			groupCurrentPage = 1;
			fetchGroupedData();
		} else {
			currentPage = 1;
			fetchData();
		}
	}

	function handleGroupFilter() {
		groupCurrentPage = 1;
		fetchGroupedData();
	}

	function groupPrevPage() {
		if (groupCurrentPage > 1) {
			groupCurrentPage--;
			fetchGroupedData();
		}
	}

	function groupNextPage() {
		if (groupCurrentPage < groupPages) {
			groupCurrentPage++;
			fetchGroupedData();
		}
	}

	function handleFilter() {
		currentPage = 1;
		selectedIds = [];
		selectAll = false;
		fetchData();
	}

	function clearFilters() {
		filterCallerType = '';
		filterRequestedBy = '';
		filterQueueName = '';
		onlyWithoutSuccess = false;
		if (viewMode === 'grouped') {
			handleGroupFilter();
		} else {
			handleFilter();
		}
	}

	function prevPage() {
		if (currentPage > 1) {
			currentPage--;
			fetchData();
		}
	}

	function nextPage() {
		if (currentPage < pages) {
			currentPage++;
			fetchData();
		}
	}

	function toggleSelectAll() {
		selectAll = !selectAll;
		if (selectAll) {
			selectedIds = requests.map(r => r.id);
		} else {
			selectedIds = [];
		}
	}

	function toggleSelect(id: number) {
		if (selectedIds.includes(id)) {
			selectedIds = selectedIds.filter(i => i !== id);
		} else {
			selectedIds = [...selectedIds, id];
		}
	}

	async function cancelRequest(id: number) {
		try {
			await llmApi.cancel(id);
			await fetchData();
		} catch (e) {
			alert('취소 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function retryRequest(id: number) {
		// quota 경고 체크 — 재시도 대상 request의 provider 기준
		const req = requests.find((r) => r.id === id);
		const provider = req?.provider || 'claude';
		const quotaWarn = getQuotaWarning(provider);
		if (quotaWarn) {
			toast.warning(quotaWarn);
		}

		try {
			await llmApi.retry(id);
			await fetchData();
		} catch (e) {
			alert('재시도 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function deleteRequest(id: number) {
		if (!confirm('이 요청을 삭제하시겠습니까?')) return;
		try {
			await llmApi.delete(id);
			await fetchData();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function batchRetry() {
		if (selectedIds.length === 0) return;
		try {
			const result = await llmApi.batchRetry(selectedIds);
			alert(`재시도 완료: 성공 ${result.success}개, 스킵 ${result.skipped}개`);
			selectedIds = [];
			selectAll = false;
			await fetchData();
		} catch (e) {
			alert('일괄 재시도 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function batchDelete() {
		if (selectedIds.length === 0) return;
		if (!confirm(`선택한 ${selectedIds.length}개 요청을 삭제하시겠습니까?`)) return;
		try {
			const result = await llmApi.batchDelete(selectedIds);
			alert(`삭제 완료: ${result.deleted}개`);
			selectedIds = [];
			selectAll = false;
			await fetchData();
		} catch (e) {
			alert('일괄 삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function runCleanup() {
		if (!confirm('Stale 요청 정리 및 오래된 이력 삭제를 실행하시겠습니까?')) return;
		try {
			const result = await llmApi.cleanup();
			alert(`정리 완료: stale ${result.stale_processing}개, 이력 ${result.old_history}개 삭제`);
			await fetchData();
		} catch (e) {
			alert('정리 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function createRequest() {
		// quota 경고 체크
		const quotaWarn = getQuotaWarning(createForm.provider);
		if (quotaWarn) {
			toast.warning(quotaWarn);
		}

		// 프리셋 사용 시 prompt 합성
		if (selectedPreset.label !== '(직접 입력)') {
			if (!createForm.userInput.trim()) {
				createError = '사용자 입력을 입력해주세요.';
				return;
			}
			const prefix = selectedPreset.promptPrefix ?? '';
		createForm.prompt = prefix + createForm.userInput;
		}

		if (!createForm.caller_id.trim() || !createForm.prompt.trim()) {
			createError = '호출자 ID와 프롬프트를 입력해주세요.';
			return;
		}

		createLoading = true;
		createError = null;
		createSuccess = false;

		try {
			// model이 "(기본)"이면 빈 문자열로 변환. userInput은 API 전송 제외.
			const { userInput: _userInput, ...formData } = createForm;
			const requestData = {
				...formData,
				model: createForm.model === '(기본)' ? '' : createForm.model
			};
			await llmApi.create(requestData);
			createSuccess = true;
			createForm = {
				caller_type: 'test',
				caller_id: '',
				prompt: '',
				queue_name: 'utility',
				requested_by: 'manual',
				request_source: 'manual_test',
				provider: 'claude',
				model: '',
				cli_options: null,
				userInput: ''
			};
			selectedPreset = presets[0];
			userInput = '';
		} catch (e) {
			createError = e instanceof Error ? e.message : '요청 생성 실패';
		} finally {
			createLoading = false;
		}
	}

	async function openModal(request: LLMRequest) {
		selectedRequest = request;
		showModal = true;
		editCwd = (request.cli_options?.cwd as string) ?? '';
		// 상세 조회 API로 raw_response 포함된 데이터 로드
		try {
			const detail = await llmApi.get(request.id);
			if (showModal && selectedRequest?.id === request.id) {
				selectedRequest = detail;
				editCwd = (detail.cli_options?.cwd as string) ?? editCwd;
			}
		} catch {
			// 실패해도 기본 데이터로 모달 유지
		}
		// pending 상태일 때 quota-status fetch
		if (request.status === 'pending') {
			try {
				quotaStatus = await llmApi.getQuotaStatus();
				const provider = request.provider || 'claude';
				const ps = quotaStatus[provider];
				if (ps?.paused && ps.remaining_seconds) {
					countdownSeconds = ps.remaining_seconds;
					countdownTimer = setInterval(() => {
						if (countdownSeconds > 0) countdownSeconds--;
					}, 1000);
				}
			} catch { /* 네트워크 오류 시 배너 미표시 */ }
		}
	}

	function closeModal() {
		showModal = false;
		selectedRequest = null;
		quotaStatus = {};
		countdownSeconds = 0;
		if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
	}

	async function updateCwd(andRetry = false) {
		if (!selectedRequest) return;
		editCwdSaving = true;
		try {
			const updated = await llmApi.update(selectedRequest.id, {
				cli_options: { ...(selectedRequest.cli_options ?? {}), cwd: editCwd }
			});
			selectedRequest = updated;
			toast.success('cwd 저장 완료');
			if (andRetry) {
				await retryRequest(selectedRequest.id);
				closeModal();
			}
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '저장 실패');
		} finally {
			editCwdSaving = false;
		}
	}

	function formatWaitTime(seconds: number): string {
		if (seconds <= 0) return '곧 재개';
		const h = Math.floor(seconds / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		const s = seconds % 60;
		if (h > 0) return `${h}시간 ${m}분`;
		if (m > 0) return `${m}분 ${s}초`;
		return `${s}초`;
	}

	function formatDateTime(isoString: string | null | undefined): string {
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

	function getStatusColor(status: string): string {
		switch (status) {
			case 'pending': return 'bg-warning-light text-warning-foreground';
			case 'processing': return 'bg-primary-light text-primary';
			case 'completed': return 'bg-success-light text-success';
			case 'failed': return 'bg-error-light text-error';
			case 'cancelled': return 'bg-muted text-foreground';
			default: return 'bg-muted text-foreground';
		}
	}

	function getStatusLabel(status: string): string {
		switch (status) {
			case 'pending': return '대기';
			case 'processing': return '처리중';
			case 'completed': return '완료';
			case 'failed': return '실패';
			case 'cancelled': return '취소';
			default: return status;
		}
	}

	function switchTab(tab: Tab) {
		// create 탭에서 작성 중인 내용이 있으면 경고
		if (activeTab === 'create' && tab !== 'create') {
			const hasContent = createForm.prompt.trim() || createForm.userInput.trim();
			if (hasContent && !confirm('작성 중인 내용이 있습니다. 탭을 전환하시겠습니까?')) {
				return;
			}
		}
		activeTab = tab;
		if (tab === 'queue' || tab === 'history') {
			currentPage = 1;
			selectedIds = [];
			selectAll = false;
			fetchData();
		}
		if (tab === 'history') {
			fetchHistoryStats();
		}
	}

	onMount(() => {
		fetchData();
		fetchQuotaStatus();
		// Provider 목록 로드
		llmApi.getProviders()
			.then(data => { providers = data; providersLoading = false; })
			.catch(() => { providersError = 'Provider 목록 로드 실패'; providersLoading = false; });
	});
</script>

<div>
	<!-- 헤더 -->
	<div class="mb-6 flex justify-between items-center">
		<h2 class="text-lg font-bold text-foreground">LLM 요청 관리</h2>
		<div class="flex gap-2">
			<Button variant="secondary" size="sm" onclick={runCleanup} title="Stale 정리 및 오래된 이력 삭제">
				정리
			</Button>
			<Button variant="secondary" size="sm" onclick={() => fetchData()}>
				새로고침
			</Button>
		</div>
	</div>

	<!-- 큐별 통계 카드 -->
	{#if queueStats}
		<div class="grid grid-cols-2 gap-4 mb-4">
			<div class="card p-4 border-l-4 border-blue-500">
				<div class="text-sm text-muted-foreground">system 대기</div>
				<div class="text-2xl font-bold text-blue-600">{queueStats.system.pending}</div>
				<div class="text-xs text-muted-foreground">우선순위 높음</div>
			</div>
			<div class="card p-4 border-l-4 border-gray-400">
				<div class="text-sm text-muted-foreground">utility 대기</div>
				<div class="text-2xl font-bold text-gray-600">{queueStats.utility.pending}</div>
				<div class="text-xs text-muted-foreground">일반 자동화</div>
			</div>
		</div>
	{/if}

	<!-- 워커 상태 및 통계 카드 -->
	{#if stats || workerStatus}
		<div class="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
			<!-- 워커 상태 -->
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">워커 상태</div>
				<div class="text-lg font-bold {workerStatus?.status === 'healthy' ? 'text-success' : workerStatus?.status === 'warning' ? 'text-warning-foreground' : workerStatus?.status === 'no_worker' ? 'text-muted-foreground' : 'text-error'}">
					{workerStatus?.status === 'healthy' ? '정상' : workerStatus?.status === 'warning' ? '지연' : workerStatus?.status === 'no_worker' ? '없음' : '비정상'}
				</div>
				{#if workerStatus?.state}
					<div class="text-xs text-muted-foreground">{workerStatus.state}</div>
				{/if}
				{#if workerStatus?.message && workerStatus?.status !== 'healthy'}
					<div class="text-xs text-muted-foreground">{workerStatus.message}</div>
				{/if}
			</div>

			<!-- 통계 카드들 -->
			{#if stats}
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">전체</div>
					<div class="text-2xl font-bold text-foreground">{stats.total}</div>
				</div>
				<div class="card p-4 {activeTab !== 'create' ? 'cursor-pointer hover:bg-warning-light' : ''}" onclick={() => activeTab !== 'create' && switchTab('queue')}>
					<div class="text-sm text-muted-foreground">대기중</div>
					<div class="text-2xl font-bold text-warning-foreground">{stats.pending}</div>
				</div>
				<div class="card p-4 {activeTab !== 'create' ? 'cursor-pointer hover:bg-primary-light' : ''}" onclick={() => activeTab !== 'create' && switchTab('queue')}>
					<div class="text-sm text-muted-foreground">처리중</div>
					<div class="text-2xl font-bold text-primary">{stats.processing}</div>
				</div>
				<div class="card p-4 {activeTab !== 'create' ? 'cursor-pointer hover:bg-success-light' : ''}" onclick={() => activeTab !== 'create' && switchTab('history')}>
					<div class="text-sm text-muted-foreground">완료</div>
					<div class="text-2xl font-bold text-success">{stats.completed}</div>
				</div>
				<div class="card p-4 {activeTab !== 'create' ? 'cursor-pointer hover:bg-error-light' : ''}" onclick={() => activeTab !== 'create' && switchTab('history')}>
					<div class="text-sm text-muted-foreground">실패</div>
					<div class="text-2xl font-bold text-error">{stats.failed}</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- 탭 -->
	<div class="mb-4 border-b border-border">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('queue')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'queue' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				대기열 (pending/processing)
			</button>
			<button
				onclick={() => switchTab('history')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'history' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				이력 (completed/failed)
			</button>
			<button
				onclick={() => switchTab('create')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'create' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				수동 요청 생성
			</button>
			<button
				onclick={() => switchTab('performance')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'performance' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				성능 분석
			</button>
			<button
				onclick={() => switchTab('claude-sessions')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'claude-sessions' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}"
			>
				Claude 세션
			</button>
		</nav>
	</div>

	{#if activeTab === 'queue' || activeTab === 'history'}
		<!-- 필터 -->
		<div class="mb-4 flex flex-wrap gap-2 items-center">
			<span class="text-sm text-muted-foreground">
				{activeTab === 'queue' ? '대기열: pending, processing' : '이력: completed, failed, cancelled'}
			</span>
			<!-- 큐 필터 버튼 -->
			<div class="flex gap-1">
				<button
					onclick={() => { filterQueueName = ''; handleFilter(); }}
					class="px-2 py-1 text-xs rounded-full border transition-colors {filterQueueName === '' ? 'bg-foreground text-background border-foreground' : 'border-border text-muted-foreground hover:border-gray-400'}"
				>전체</button>
				<button
					onclick={() => { filterQueueName = 'system'; handleFilter(); }}
					class="px-2 py-1 text-xs rounded-full border transition-colors {filterQueueName === 'system' ? 'bg-blue-600 text-white border-blue-600' : 'border-border text-muted-foreground hover:border-blue-400'}"
				>system</button>
				<button
					onclick={() => { filterQueueName = 'utility'; handleFilter(); }}
					class="px-2 py-1 text-xs rounded-full border transition-colors {filterQueueName === 'utility' ? 'bg-gray-500 text-white border-gray-500' : 'border-border text-muted-foreground hover:border-gray-400'}"
				>utility</button>
			</div>
			<select bind:value={filterCallerType} class="px-3 py-1.5 border border-border rounded-lg text-sm">
				<option value="">전체 타입</option>
				<option value="instagram">Instagram</option>
				<option value="test">Test</option>
			</select>
			{#if activeTab === 'history' && viewMode === 'individual'}
				<input
					type="text"
					placeholder="요청자"
					bind:value={filterRequestedBy}
					class="px-3 py-1.5 border border-border rounded-lg text-sm"
				/>
			{/if}
			{#if activeTab === 'queue'}
				<input
					type="text"
					placeholder="요청자"
					bind:value={filterRequestedBy}
					class="px-3 py-1.5 border border-border rounded-lg text-sm"
				/>
			{/if}
			{#if activeTab === 'history' && viewMode === 'grouped'}
				<label class="flex items-center gap-1 text-sm">
					<input
						type="checkbox"
						bind:checked={onlyWithoutSuccess}
						onchange={handleGroupFilter}
						class="rounded"
					/>
					성공 없는 것만
				</label>
			{/if}
			<Button variant="primary" size="sm" onclick={viewMode === 'grouped' ? handleGroupFilter : handleFilter}>필터</Button>
			<Button variant="secondary" size="sm" onclick={clearFilters}>초기화</Button>

			{#if activeTab === 'history'}
				<div class="ml-auto flex items-center gap-2">
					<Button
						variant={viewMode === 'grouped' ? 'primary' : 'secondary'}
						size="sm"
						onclick={toggleViewMode}
					>
						{viewMode === 'individual' ? '그룹 뷰' : '개별 뷰'}
					</Button>
				</div>
			{/if}
		</div>

		<!-- 그룹 뷰 요약 및 일괄 재시도 버튼 -->
		{#if activeTab === 'history' && viewMode === 'grouped' && groupedResponse}
			<div class="mb-4 flex gap-4 items-center p-3 bg-background rounded-lg flex-wrap">
				<div class="text-sm">
					<span class="text-muted-foreground">전체:</span>
					<span class="font-bold text-foreground">{groupedResponse.summary.total_callers}</span>
				</div>
				<div class="text-sm">
					<span class="text-success">성공 있음:</span>
					<span class="font-bold text-success">{groupedResponse.summary.callers_with_success}</span>
				</div>
				<div class="text-sm">
					<span class="text-error">성공 없음:</span>
					<span class="font-bold text-error">{groupedResponse.summary.callers_without_success}</span>
				</div>
				<div class="ml-auto flex gap-2">
					{#if selectedGroupKeys.length > 0}
						<span class="text-sm text-muted-foreground self-center">{selectedGroupKeys.length}개 선택</span>
						<Button variant="secondary" size="sm" onclick={multiRetrySelectedGroups}>
							선택 그룹 재시도
						</Button>
					{/if}
					{#if groupedResponse.summary.callers_without_success > 0}
						<Button variant="primary" size="sm" onclick={retryAllFailedWithoutSuccess}>
							성공 없는 것 일괄 재시도
						</Button>
					{/if}
				</div>
			</div>
		{/if}

		<!-- 일괄 작업 버튼 (개별 뷰) -->
		{#if viewMode === 'individual' && selectedIds.length > 0}
			<div class="mb-4 flex gap-2 items-center">
				<span class="text-sm text-muted-foreground">{selectedIds.length}개 선택</span>
				{#if activeTab === 'history'}
					<Button variant="secondary" size="sm" onclick={batchRetry}>일괄 재시도</Button>
				{/if}
				<button onclick={batchDelete} class="btn btn-danger btn-sm">일괄 삭제</button>
			</div>
		{/if}

		{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
		{:else if activeTab === 'history' && viewMode === 'grouped'}
			<!-- 그룹 뷰 테이블 -->
			{#if callerGroups.length === 0}
				<div class="text-center py-12 text-muted-foreground">
					<p class="text-lg">그룹화된 이력이 없습니다</p>
				</div>
			{:else}
				<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
					<table class="w-full min-w-[900px]">
						<thead class="bg-background border-b border-border">
							<tr>
								<th class="px-4 py-3 text-left whitespace-nowrap">
									<input
										type="checkbox"
										checked={groupSelectAll}
										onchange={toggleGroupSelectAll}
										class="rounded"
									/>
								</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">타입</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">호출자 ID</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청내용</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청 수</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">성공</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">실패</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">대기</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">성공 여부</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">최근 상태</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">마지막 요청</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each callerGroups as group}
								<tr class="hover:bg-muted {group.has_success ? '' : 'bg-error-light'}">
									<td class="px-4 py-3">
										<input
											type="checkbox"
											checked={selectedGroupKeys.includes(getGroupKey(group))}
											onchange={() => toggleGroupSelect(group)}
											class="rounded"
										/>
									</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">{group.caller_type}</td>
									<td class="px-4 py-3 text-sm text-foreground font-mono">{group.caller_id}</td>
									<td class="px-4 py-3 text-sm text-foreground max-w-xs truncate" title={group.prompt}>
										{truncatePrompt(group.prompt)}
									</td>
									<td class="px-4 py-3 text-sm text-foreground font-bold">{group.total_count}</td>
									<td class="px-4 py-3 text-sm text-success font-bold">{group.completed_count}</td>
									<td class="px-4 py-3 text-sm text-error font-bold">{group.failed_count}</td>
									<td class="px-4 py-3 text-sm text-warning-foreground">{group.pending_count}</td>
									<td class="px-4 py-3">
										{#if group.has_success}
											<span class="px-2 py-1 text-xs rounded-full bg-success-light text-success">있음</span>
										{:else}
											<span class="px-2 py-1 text-xs rounded-full bg-error-light text-error">없음</span>
										{/if}
									</td>
									<td class="px-4 py-3">
										<span class="px-2 py-1 text-xs rounded-full {getStatusColor(group.last_status)}">
											{getStatusLabel(group.last_status)}
										</span>
									</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(group.last_requested_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- 그룹 뷰 페이지네이션 -->
				{#if groupPages > 1}
					<div class="flex justify-between items-center">
						<span class="text-sm text-muted-foreground">
							전체 {groupTotal}개 중 {(groupCurrentPage - 1) * groupPageSize + 1} - {Math.min(groupCurrentPage * groupPageSize, groupTotal)}
						</span>
						<div class="flex gap-2">
							<button
								onclick={groupPrevPage}
								disabled={groupCurrentPage === 1}
								class="btn btn-secondary btn-sm disabled:opacity-50"
							>
								이전
							</button>
							<span class="px-3 py-1.5 text-sm">{groupCurrentPage} / {groupPages}</span>
							<button
								onclick={groupNextPage}
								disabled={groupCurrentPage >= groupPages}
								class="btn btn-secondary btn-sm disabled:opacity-50"
							>
								다음
							</button>
						</div>
					</div>
				{/if}
			{/if}
		{:else if requests.length === 0}
			<div class="text-center py-12 text-muted-foreground">
				<p class="text-lg">{activeTab === 'queue' ? '대기열이 비어있습니다' : '이력이 없습니다'}</p>
			</div>
		{:else}
			<!-- 개별 요청 목록 테이블 -->
			<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
				<table class="w-full min-w-[700px]">
					<thead class="bg-background border-b border-border">
						<tr>
							<th class="px-4 py-3 text-left whitespace-nowrap">
								<input
									type="checkbox"
									checked={selectAll}
									onchange={toggleSelectAll}
									class="rounded"
								/>
							</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">큐</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">타입</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">호출자 ID</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청자</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">Provider</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">상태</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청시간</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each requests as request (request.id)}
							<tr
								class="hover:bg-muted cursor-pointer"
								onclick={() => openModal(request)}
							>
								<td class="px-4 py-3" onclick={(e) => e.stopPropagation()}>
									<input
										type="checkbox"
										checked={selectedIds.includes(request.id)}
										onchange={() => toggleSelect(request.id)}
										class="rounded"
									/>
								</td>
								<td class="px-4 py-3 text-sm text-foreground">{request.id}</td>
								<td class="px-4 py-3">
									{#if request.queue_name === 'system'}
										<span class="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700">system</span>
									{:else}
										<span class="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">utility</span>
									{/if}
								</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{request.caller_type}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{request.caller_id}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{request.requested_by || '-'}</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">
									{request.provider ? (request.provider === 'claude' ? 'Claude' : 'Gemini') : 'Claude'}
								</td>
								<td class="px-4 py-3">
									<span class="px-2 py-1 text-xs rounded-full {getStatusColor(request.status)}">
										{getStatusLabel(request.status)}
									</span>
								</td>
								<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(request.requested_at)}</td>
								<td class="px-4 py-3" onclick={(e) => e.stopPropagation()}>
									<div class="flex gap-1">
										{#if request.status === 'pending'}
											<button
												onclick={() => cancelRequest(request.id)}
												class="text-warning-foreground hover:text-warning-foreground text-sm"
											>
												취소
											</button>
										{/if}
										{#if request.status === 'failed' || request.status === 'completed'}
											<button
												onclick={() => retryRequest(request.id)}
												class="text-primary hover:text-primary-hover text-sm"
											>
												{request.status === 'completed' ? '재분석' : '재시도'}
											</button>
										{/if}
										<button
											onclick={() => deleteRequest(request.id)}
											class="text-error hover:text-error text-sm"
										>
											삭제
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- 페이지네이션 -->
			{#if pages > 1}
				<div class="flex justify-between items-center">
					<span class="text-sm text-muted-foreground">
						전체 {total}개 중 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)}
					</span>
					<div class="flex gap-2">
						<button
							onclick={prevPage}
							disabled={currentPage === 1}
							class="btn btn-secondary btn-sm disabled:opacity-50"
						>
							이전
						</button>
						<span class="px-3 py-1.5 text-sm">{currentPage} / {pages}</span>
						<button
							onclick={nextPage}
							disabled={currentPage >= pages}
							class="btn btn-secondary btn-sm disabled:opacity-50"
						>
							다음
						</button>
					</div>
				</div>
			{/if}
		{/if}

		<!-- 이력 탭의 통계 -->
		{#if activeTab === 'history' && historyStats}
			<div class="mt-8">
				<h3 class="text-lg font-bold text-foreground mb-4">7일간 통계</h3>
				<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
					<div class="card p-4">
						<div class="text-sm text-muted-foreground">총 요청</div>
						<div class="text-2xl font-bold text-foreground">{historyStats.summary.total}</div>
					</div>
					<div class="card p-4">
						<div class="text-sm text-muted-foreground">성공률</div>
						<div class="text-2xl font-bold text-success">{historyStats.summary.success_rate}%</div>
					</div>
					<div class="card p-4">
						<div class="text-sm text-muted-foreground">완료</div>
						<div class="text-2xl font-bold text-success">{historyStats.summary.completed}</div>
					</div>
					<div class="card p-4">
						<div class="text-sm text-muted-foreground">평균 처리 시간</div>
						<div class="text-2xl font-bold text-primary">{historyStats.summary.avg_processing_time_seconds}s</div>
					</div>
				</div>
			</div>
		{/if}
	{:else if activeTab === 'create'}
		<!-- 수동 요청 생성 폼 -->
		<div class="max-w-2xl">
			<div class="bg-white rounded-lg border border-border p-6">
				<h3 class="text-lg font-bold text-foreground mb-4">수동 LLM 요청 생성</h3>
				<p class="text-sm text-muted-foreground mb-6">테스트 또는 디버깅 목적으로 수동으로 LLM 요청을 생성합니다.</p>

				{#if createSuccess}
					<div class="mb-4 p-4 bg-success-light border border-green-200 text-success rounded-lg flex items-center justify-between">
						<span>요청이 성공적으로 생성되었습니다.</span>
						<button
							type="button"
							onclick={() => { createSuccess = false; activeTab = 'queue'; fetchData(); }}
							class="text-sm underline hover:no-underline font-medium"
						>대기열에서 확인</button>
					</div>
				{/if}

				{#if createError}
					<div class="mb-4 p-4 bg-error-light border border-red-200 text-error rounded-lg">
						{createError}
					</div>
				{/if}

				<div class="space-y-4">
					<!-- 프리셋 선택 -->
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">프리셋</label>
						<select
							value={selectedPreset.label}
							onchange={(e) => {
								const found = presets.find(p => p.label === (e.target as HTMLSelectElement).value);
								if (found) applyPreset(found);
							}}
							class="w-full px-3 py-2 border border-border rounded-lg"
						>
							{#each presets as preset}
								<option value={preset.label}>{preset.label}</option>
							{/each}
						</select>
					</div>

					<div>
						<label class="block text-sm font-medium text-foreground mb-1">큐</label>
						<select bind:value={createForm.queue_name} class="w-full px-3 py-2 border border-border rounded-lg">
							<option value="utility">utility (일반 자동화)</option>
							<option value="system">system (시스템/개발, 우선순위 높음)</option>
						</select>
					</div>

					<div>
						<label class="block text-sm font-medium text-foreground mb-1">호출자 타입</label>
						<select bind:value={createForm.caller_type} class="w-full px-3 py-2 border border-border rounded-lg">
							<option value="test">test</option>
							<option value="instagram">instagram</option>
						</select>
					</div>

					<div>
						<label class="block text-sm font-medium text-foreground mb-1">호출자 ID *</label>
						<input
							type="text"
							bind:value={createForm.caller_id}
							placeholder="예: 123"
							class="w-full px-3 py-2 border border-border rounded-lg"
						/>
					</div>

					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-sm font-medium text-foreground mb-1">Provider</label>
							{#if providersError}
								<p class="text-sm text-red-500">{providersError}</p>
							{:else if providersLoading}
								<p class="text-sm text-muted-foreground">로딩 중...</p>
							{:else}
								<select bind:value={createForm.provider} class="w-full px-3 py-2 border border-border rounded-lg">
									{#each providers as p}
										<option value={p.key}>{p.display_name}</option>
									{/each}
								</select>
							{/if}
						</div>
						<div>
							<label class="block text-sm font-medium text-foreground mb-1">Model</label>
							<select bind:value={createForm.model} class="w-full px-3 py-2 border border-border rounded-lg">
								{#each getProviderModels(createForm.provider) as modelOption}
									<option value={modelOption === '(기본)' ? '' : modelOption}>
										{modelOption}
									</option>
								{/each}
							</select>
						</div>
					</div>

					{#if selectedPreset.label === '(직접 입력)'}
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">프롬프트 *</label>
						<textarea
							bind:value={createForm.prompt}
							rows="6"
							placeholder="LLM에 전달할 프롬프트를 입력하세요..."
							class="w-full px-3 py-2 border border-border rounded-lg resize-none"
						></textarea>
					</div>
					{:else}
					<div>
						<textarea
							bind:value={createForm.userInput}
							rows="6"
							placeholder={selectedPreset.userPromptPlaceholder ?? '내용을 입력하세요...'}
							class="w-full px-3 py-2 border border-border rounded-lg resize-none"
						></textarea>
					</div>
					{/if}

					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-sm font-medium text-foreground mb-1">요청자</label>
							<input
								type="text"
								bind:value={createForm.requested_by}
								class="w-full px-3 py-2 border border-border rounded-lg"
							/>
						</div>
						<div>
							<label class="block text-sm font-medium text-foreground mb-1">출처</label>
							<input
								type="text"
								bind:value={createForm.request_source}
								class="w-full px-3 py-2 border border-border rounded-lg"
							/>
						</div>
					</div>

					<div class="pt-4">
						<button
							onclick={createRequest}
							disabled={createLoading}
							class="btn btn-primary w-full disabled:opacity-50"
						>
							{createLoading ? '생성 중...' : '요청 생성'}
						</button>
					</div>
				</div>
			</div>
		</div>
	{:else if activeTab === 'performance'}
		<LLMPerformance />
	{:else if activeTab === 'claude-sessions'}
		<ClaudeSessionsTab />
	{/if}
</div>

<!-- 상세 모달 -->
{#if showModal && selectedRequest}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeModal}
		onkeydown={(e) => e.key === 'Escape' && closeModal()}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<div>
						<h3 class="text-lg font-bold text-foreground">요청 상세 #{selectedRequest.id}</h3>
						<span class="px-2 py-1 text-xs rounded-full {getStatusColor(selectedRequest.status)}">
							{getStatusLabel(selectedRequest.status)}
						</span>
					</div>
					<button onclick={closeModal} class="text-muted-foreground hover:text-muted-foreground text-2xl">
						&times;
					</button>
				</div>

				<div class="grid grid-cols-2 gap-4 text-sm mb-4">
					<div>
						<span class="text-muted-foreground">타입:</span>
						<span class="ml-1">{selectedRequest.caller_type}</span>
					</div>
					<div>
						<span class="text-muted-foreground">호출자 ID:</span>
						<span class="ml-1">{selectedRequest.caller_id}</span>
					</div>
					<div>
						<span class="text-muted-foreground">요청자:</span>
						<span class="ml-1">{selectedRequest.requested_by || '-'}</span>
					</div>
					<div>
						<span class="text-muted-foreground">출처:</span>
						<span class="ml-1">{selectedRequest.request_source || '-'}</span>
					</div>
					<div>
						<span class="text-muted-foreground">Provider:</span>
						<span class="ml-1">{selectedRequest.provider || 'claude'}</span>
					</div>
					<div>
						<span class="text-muted-foreground">Model:</span>
						<span class="ml-1">{selectedRequest.model || '(기본)'}</span>
					</div>
					<div>
						<span class="text-muted-foreground">요청 시간:</span>
						<span class="ml-1">{formatDateTime(selectedRequest.requested_at)}</span>
					</div>
					<div>
						<span class="text-muted-foreground">처리 시간:</span>
						<span class="ml-1">{formatDateTime(selectedRequest.processed_at)}</span>
					</div>
					<div>
						<span class="text-muted-foreground">재시도 횟수:</span>
						<span class="ml-1">{selectedRequest.retry_count}</span>
					</div>
				</div>

				{#if selectedRequest.status === 'pending'}
					{@const provider = selectedRequest.provider || 'claude'}
					{@const ps = quotaStatus[provider]}
					{#if ps?.paused}
						<div class="mb-4 p-3 bg-warning-light rounded-lg flex items-start gap-2">
							<span class="text-warning-foreground text-sm font-medium">⏸ {provider === 'gemini' ? 'Gemini' : 'Claude'} 쿼터 소진</span>
							<span class="text-warning-foreground text-sm ml-auto">{formatWaitTime(countdownSeconds)} 후 재개</span>
						</div>
					{:else}
						<div class="mb-4 p-3 bg-muted rounded-lg">
							<span class="text-muted-foreground text-sm">⏳ 처리 대기 중</span>
						</div>
					{/if}
				{/if}

				{#if selectedRequest.status === 'pending' || selectedRequest.status === 'failed'}
					<div class="mb-4 p-3 bg-muted rounded-lg">
						<div class="text-sm font-medium text-foreground mb-1">실행 경로 (cwd)</div>
						<div class="flex gap-2">
							<input
								type="text"
								bind:value={editCwd}
								class="input input-sm flex-1 font-mono text-xs"
								placeholder="D:/work/project/..."
							/>
							{#if selectedRequest.status === 'failed'}
								<button
									onclick={() => updateCwd(true)}
									disabled={editCwdSaving}
									class="btn btn-primary btn-sm whitespace-nowrap"
								>
									{editCwdSaving ? '저장중...' : '저장 후 재시도'}
								</button>
							{:else}
								<button
									onclick={() => updateCwd(false)}
									disabled={editCwdSaving}
									class="btn btn-secondary btn-sm"
								>
									{editCwdSaving ? '저장중...' : '저장'}
								</button>
							{/if}
						</div>
					</div>
				{/if}

				{#if selectedRequest.error_message}
					<div class="mb-4 p-3 bg-error-light rounded-lg">
						<div class="text-sm font-medium text-error mb-1">에러 메시지</div>
						<p class="text-sm text-error whitespace-pre-wrap">{selectedRequest.error_message}</p>
					</div>
				{/if}

				{#if selectedRequest.result}
					<div class="mb-4 p-3 bg-background rounded-lg">
						<div class="text-sm font-medium text-foreground mb-1">결과</div>
						<pre class="text-sm text-foreground whitespace-pre-wrap overflow-auto max-h-64">{JSON.stringify(selectedRequest.result, null, 2)}</pre>
					</div>
				{/if}

				{#if selectedRequest.raw_response}
					<div class="mb-4 p-3 bg-background rounded-lg">
						<div class="flex items-center justify-between mb-1">
							<div class="text-sm font-medium text-foreground">LLM 원본 응답</div>
							<span class="text-xs text-muted-foreground">{selectedRequest.raw_response.length.toLocaleString()}자</span>
						</div>
						<pre class="text-xs text-muted-foreground whitespace-pre-wrap overflow-auto max-h-96 border border-border rounded p-2">{selectedRequest.raw_response}</pre>
					</div>
				{/if}

				<div class="flex gap-2 flex-wrap">
					{#if selectedRequest.status === 'pending'}
						<button
							onclick={() => { cancelRequest(selectedRequest!.id); closeModal(); }}
							class="btn btn-secondary btn-sm"
						>
							취소
						</button>
					{/if}
					{#if selectedRequest.status === 'failed' || selectedRequest.status === 'completed'}
						<button
							onclick={() => { retryRequest(selectedRequest!.id); closeModal(); }}
							class="btn btn-primary btn-sm"
						>
							{selectedRequest.status === 'completed' ? '재분석' : '재시도'}
						</button>
					{/if}
					<button
						onclick={() => { deleteRequest(selectedRequest!.id); closeModal(); }}
						class="btn btn-danger btn-sm"
					>
						삭제
					</button>
					<Button variant="secondary" size="sm" onclick={closeModal}>닫기</Button>
				</div>
			</div>
		</div>
	</div>
{/if}
