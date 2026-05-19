<script lang="ts">
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import { onMount } from 'svelte';
	import {
		llmApi,
		type LLMBootstrapResponse,
		type LLMRequest,
		type LLMStats,
		type LLMWorkerStatus,
		type LLMHistoryStats,
		type LLMQueueStats,
		type LLMCallerGroup,
		type LLMGroupedListResponse,
		type QuotaStatusMap,
		type ProviderInfo,
		type LLMProfileConfig,
		type LLMScheduleProfilePolicyItem
	} from '$lib/api';
	import { toast } from '$lib/stores/toast';
	import { confirm } from '$lib/stores/confirm';
	import { fetchQuotaStatus, getQuotaWarning } from '$lib/stores/quotaStore';
	import LlmCreateRequestPanel from './components/LlmCreateRequestPanel.svelte';
	import LlmOverviewPanel from './components/LlmOverviewPanel.svelte';
	import LlmPolicyPanel from './components/LlmPolicyPanel.svelte';
	import LlmRequestDetailModal from './components/LlmRequestDetailModal.svelte';
	import LlmRequestsPanel from './components/LlmRequestsPanel.svelte';
	import {
		errorMessage,
		getGroupKey,
		getProviderModels,
		parsePolicyWindows,
		profileOptionsForEngine
	} from './helpers';
	import type { LlmCreateForm, LlmPolicyForm, LlmPreset, LlmTabId } from './types';

	let requests = $state<LLMRequest[]>([]);
	let stats = $state<LLMStats | null>(null);
	let workerStatus = $state<LLMWorkerStatus | null>(null);
	let historyStats = $state<LLMHistoryStats | null>(null);
	let queueStats = $state<LLMQueueStats | null>(null);

	let callerGroups = $state<LLMCallerGroup[]>([]);
	let groupedResponse = $state<LLMGroupedListResponse | null>(null);
	let viewMode = $state<'individual' | 'grouped'>('individual');
	let onlyWithoutSuccess = $state(false);

	let loading = $state(true);
	let error = $state<string | null>(null);
	let initialAutoSwitchHandled = false;
	let requestFetchSeq = 0;
	let groupFetchSeq = 0;

	let currentPage = $state(1);
	const pageSize = 20;
	let total = $state(0);
	let pages = $state(0);

	let groupCurrentPage = $state(1);
	const groupPageSize = 50;
	let groupTotal = $state(0);
	let groupPages = $state(0);

	let selectedGroupKeys = $state<string[]>([]);
	let groupSelectAll = $state(false);

	let filterCallerType = $state('');
	let filterRequestedBy = $state('');
	let filterQueueName = $state('');

	let selectedIds = $state<number[]>([]);
	let selectAll = $state(false);

	let activeTab = $state<LlmTabId>('queue');
	const llmTabs = [
		{ id: 'queue', label: '대기열', shortLabel: '대기' },
		{ id: 'history', label: '이력', shortLabel: '이력' },
		{ id: 'create', label: '수동 요청 생성', shortLabel: '생성' },
		{ id: 'profilePolicy', label: 'Profile 정책', shortLabel: '정책' },
		{ id: 'performance', label: '성능 분석', shortLabel: '성능' },
		{ id: 'claude-sessions', label: 'Claude 세션', shortLabel: '세션' }
	];

	let selectedRequest = $state<LLMRequest | null>(null);
	let showModal = $state(false);
	let editCwd = $state('');
	let editCwdSaving = $state(false);
	let quotaStatus = $state<QuotaStatusMap>({});
	let countdownSeconds = $state(0);
	let countdownTimer: ReturnType<typeof setInterval> | null = null;
	let createMetaLoaded = false;
	let createMetaLoading = false;
	let performanceTabComponent = $state<any | null>(null);
	let claudeSessionsTabComponent = $state<any | null>(null);

	let createForm = $state<LlmCreateForm>(initialCreateForm());
	let createLoading = $state(false);
	let createError = $state<string | null>(null);
	let createSuccess = $state(false);

	let profilePolicies = $state<LLMScheduleProfilePolicyItem[]>([]);
	let policyProfiles = $state<LLMProfileConfig[]>([]);
	let policyLoading = $state(false);
	let policySaving = $state(false);
	let policyError = $state<string | null>(null);
	let policyForm = $state<LlmPolicyForm>({
		target_type: 'plan_archive_analyze',
		engine: 'claude',
		profile_name: '',
		enabled: true,
		priority: 0,
		allowed_windows_text: '',
		quiet_windows_text: ''
	});

	let providers = $state<ProviderInfo[]>([]);
	let providersLoading = $state(true);
	let providersError = $state<string | null>(null);

	const presets: LlmPreset[] = [
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
	let selectedPreset = $state<LlmPreset>(presets[0]);

	function initialCreateForm(): LlmCreateForm {
		return {
			caller_type: 'test',
			caller_id: '',
			prompt: '',
			queue_name: 'utility',
			requested_by: 'manual',
			request_source: 'manual_test',
			provider: 'claude',
			model: '',
			cli_options: undefined,
			userInput: ''
		};
	}

	function applyPreset(preset: LlmPreset) {
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
		createForm.cli_options = preset.cliOptions ?? undefined;
		if (preset.label === '(직접 입력)') {
			createForm.prompt = '';
		}
	}

	let previousProvider = createForm.provider;
	$effect(() => {
		if (createForm.provider !== previousProvider) {
			previousProvider = createForm.provider;
			createForm.model = '';
		}
	});

	let previousPolicyEngine = policyForm.engine;
	$effect(() => {
		if (policyForm.engine !== previousPolicyEngine) {
			previousPolicyEngine = policyForm.engine;
			policyForm.profile_name = '';
			ensurePolicyFormProfile();
		}
	});

	function getStatusFilter(): string | undefined {
		if (activeTab === 'queue') return 'pending,processing';
		if (activeTab === 'history') return 'completed,failed,cancelled';
		return undefined;
	}

	function shouldAutoSwitchToHistory(bootstrapRes: LLMBootstrapResponse): boolean {
		if (initialAutoSwitchHandled) return false;
		if (activeTab !== 'queue') return false;
		if (currentPage !== 1) return false;
		if (filterCallerType || filterRequestedBy || filterQueueName) return false;
		if (bootstrapRes.list.total > 0) return false;
		return (bootstrapRes.stats.completed + bootstrapRes.stats.failed) > 0;
	}

	async function loadCreateMeta() {
		if (createMetaLoaded || createMetaLoading) return;
		createMetaLoading = true;
		providersLoading = true;
		providersError = null;
		try {
			await fetchQuotaStatus(true);
			providers = await llmApi.getProviders();
			createMetaLoaded = true;
		} catch (e) {
			providersError = e instanceof Error ? e.message : 'Provider 목록 로드 실패';
		} finally {
			providersLoading = false;
			createMetaLoading = false;
		}
	}

	async function loadPerformanceTabComponent() {
		if (performanceTabComponent) return;
		try {
			performanceTabComponent = (await import('$lib/components/LLMPerformance.svelte')).default;
		} catch (e) {
			console.error('성능 탭 컴포넌트 로드 실패:', e);
		}
	}

	async function loadClaudeSessionsTabComponent() {
		if (claudeSessionsTabComponent) return;
		try {
			claudeSessionsTabComponent = (await import('./ClaudeSessionsTab.svelte')).default;
		} catch (e) {
			console.error('Claude 세션 탭 컴포넌트 로드 실패:', e);
		}
	}

	async function fetchData() {
		const seq = ++requestFetchSeq;
		loading = true;
		error = null;
		try {
			const bootstrapRes: LLMBootstrapResponse = await llmApi.bootstrap({
				status: getStatusFilter(),
				caller_type: filterCallerType || undefined,
				requested_by: filterRequestedBy || undefined,
				queue_name: filterQueueName || undefined,
				page: currentPage,
				page_size: pageSize
			});

			if (seq !== requestFetchSeq) return;

			if (shouldAutoSwitchToHistory(bootstrapRes)) {
				initialAutoSwitchHandled = true;
				activeTab = 'history';
				await fetchHistoryStats();
				await fetchData();
				return;
			}

			requests = bootstrapRes.list.items;
			total = bootstrapRes.list.total;
			pages = bootstrapRes.list.pages || 1;
			stats = bootstrapRes.stats;
			workerStatus = bootstrapRes.worker_status;
			queueStats = bootstrapRes.queue_stats;
			try {
				quotaStatus = await llmApi.getQuotaStatus();
			} catch {
				quotaStatus = {};
			}
			initialAutoSwitchHandled = true;
		} catch (e) {
			if (seq === requestFetchSeq) {
				error = e instanceof Error ? e.message : '데이터 로드 실패';
			}
		} finally {
			if (seq === requestFetchSeq) {
				loading = false;
			}
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
		const seq = ++groupFetchSeq;
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

			if (seq !== groupFetchSeq) return;

			callerGroups = res.items;
			groupedResponse = res;
			groupTotal = res.total;
			groupPages = res.pages;
			stats = statsRes;
			workerStatus = workerRes;
		} catch (e) {
			if (seq === groupFetchSeq) {
				error = e instanceof Error ? e.message : '데이터 로드 실패';
			}
		} finally {
			if (seq === groupFetchSeq) {
				loading = false;
			}
		}
	}

	async function retryAllFailedWithoutSuccess() {
		if (!await confirm({ title: '일괄 재시도', message: '성공한 적 없는 모든 caller의 실패 요청을 재시도하시겠습니까?', confirmText: '재시도' })) return;
		try {
			const result = await llmApi.retryFailedCallersWithoutSuccess(filterCallerType || undefined);
			toast.success(`재시도 완료: ${result.retried}개 요청 (${result.callers}개 caller)`);
			await fetchGroupedData();
		} catch (e) {
			toast.error('재시도 실패: ' + errorMessage(e));
		}
	}

	function toggleGroupSelectAll() {
		groupSelectAll = !groupSelectAll;
		selectedGroupKeys = groupSelectAll ? callerGroups.map(group => getGroupKey(group)) : [];
	}

	function toggleGroupSelect(group: LLMCallerGroup) {
		const key = getGroupKey(group);
		selectedGroupKeys = selectedGroupKeys.includes(key)
			? selectedGroupKeys.filter(selectedKey => selectedKey !== key)
			: [...selectedGroupKeys, key];
	}

	async function multiRetrySelectedGroups() {
		if (selectedGroupKeys.length === 0) return;

		const selectedGroups = callerGroups.filter(group => selectedGroupKeys.includes(getGroupKey(group)));
		const failedRequestIds = selectedGroups.flatMap(group => group.request_ids);

		if (failedRequestIds.length === 0) {
			toast.warning('선택된 그룹에 재시도할 실패 요청이 없습니다.');
			return;
		}

		if (!await confirm({ title: '선택 그룹 재시도', message: `선택된 ${selectedGroups.length}개 그룹의 ${failedRequestIds.length}개 실패 요청을 재시도하시겠습니까?`, confirmText: '재시도' })) return;

		try {
			const result = await llmApi.batchRetry(failedRequestIds);
			toast.success(`재시도 완료: 성공 ${result.success}개, 스킵 ${result.skipped}개`);
			selectedGroupKeys = [];
			groupSelectAll = false;
			await fetchGroupedData();
		} catch (e) {
			toast.error('일괄 재시도 실패: ' + errorMessage(e));
		}
	}

	function toggleViewMode() {
		viewMode = viewMode === 'individual' ? 'grouped' : 'individual';
		if (viewMode === 'grouped') {
			groupCurrentPage = 1;
			void fetchGroupedData();
		} else {
			currentPage = 1;
			void fetchData();
		}
	}

	function handleGroupFilter() {
		groupCurrentPage = 1;
		void fetchGroupedData();
	}

	function groupPrevPage() {
		if (groupCurrentPage > 1) {
			groupCurrentPage--;
			void fetchGroupedData();
		}
	}

	function groupNextPage() {
		if (groupCurrentPage < groupPages) {
			groupCurrentPage++;
			void fetchGroupedData();
		}
	}

	function handleFilter() {
		currentPage = 1;
		selectedIds = [];
		selectAll = false;
		void fetchData();
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
			void fetchData();
		}
	}

	function nextPage() {
		if (currentPage < pages) {
			currentPage++;
			void fetchData();
		}
	}

	function toggleSelectAll() {
		selectAll = !selectAll;
		selectedIds = selectAll ? requests.map(request => request.id) : [];
	}

	function toggleSelect(id: number) {
		selectedIds = selectedIds.includes(id)
			? selectedIds.filter(selectedId => selectedId !== id)
			: [...selectedIds, id];
	}

	async function cancelRequest(id: number) {
		try {
			await llmApi.cancel(id);
			await fetchData();
		} catch (e) {
			toast.error('취소 실패: ' + errorMessage(e));
		}
	}

	async function retryRequest(id: number) {
		const req = requests.find(request => request.id === id) ?? (selectedRequest?.id === id ? selectedRequest : null);
		const provider = req?.provider || 'claude';
		const quotaWarn = getQuotaWarning(provider);
		if (quotaWarn) {
			toast.warning(quotaWarn);
		}

		try {
			await llmApi.retry(id);
			await fetchData();
		} catch (e) {
			toast.error('재시도 실패: ' + errorMessage(e));
		}
	}

	async function deleteRequest(id: number) {
		if (!await confirm({ title: '요청 삭제', message: '이 요청을 삭제하시겠습니까?', confirmText: '삭제', variant: 'danger' })) return;
		try {
			await llmApi.delete(id);
			selectedIds = selectedIds.filter(selectedId => selectedId !== id);
			if (selectedRequest?.id === id) {
				closeModal();
			}
			await fetchData();
		} catch (e) {
			toast.error('삭제 실패: ' + errorMessage(e));
		}
	}

	async function batchRetry() {
		if (selectedIds.length === 0) return;
		try {
			const result = await llmApi.batchRetry(selectedIds);
			toast.success(`재시도 완료: 성공 ${result.success}개, 스킵 ${result.skipped}개`);
			selectedIds = [];
			selectAll = false;
			await fetchData();
		} catch (e) {
			toast.error('일괄 재시도 실패: ' + errorMessage(e));
		}
	}

	async function batchDelete() {
		if (selectedIds.length === 0) return;
		if (!await confirm({ title: '일괄 삭제', message: `선택한 ${selectedIds.length}개 요청을 삭제하시겠습니까?`, confirmText: '삭제', variant: 'danger' })) return;
		try {
			const deletingIds = selectedIds;
			const result = await llmApi.batchDelete(deletingIds);
			toast.success(`삭제 완료: ${result.deleted}개`);
			if (selectedRequest && deletingIds.includes(selectedRequest.id)) {
				closeModal();
			}
			selectedIds = [];
			selectAll = false;
			await fetchData();
		} catch (e) {
			toast.error('일괄 삭제 실패: ' + errorMessage(e));
		}
	}

	async function runCleanup() {
		if (!await confirm({ title: '요청 정리', message: 'Stale 요청 정리 및 오래된 이력 삭제를 실행하시겠습니까?', confirmText: '정리', variant: 'danger' })) return;
		try {
			const result = await llmApi.cleanup();
			toast.success(`정리 완료: stale ${result.stale_processing}개, 이력 ${result.old_history}개 삭제`);
			await fetchData();
		} catch (e) {
			toast.error('정리 실패: ' + errorMessage(e));
		}
	}

	async function createRequest() {
		const quotaWarn = getQuotaWarning(createForm.provider);
		if (quotaWarn) {
			toast.warning(quotaWarn);
		}

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
			const { userInput: _userInput, ...formData } = createForm;
			const requestData = {
				...formData,
				model: createForm.model === '(기본)' ? '' : createForm.model
			};
			await llmApi.create(requestData);
			createSuccess = true;
			createForm = initialCreateForm();
			selectedPreset = presets[0];
		} catch (e) {
			createError = e instanceof Error ? e.message : '요청 생성 실패';
		} finally {
			createLoading = false;
		}
	}

	async function showCreatedRequestInQueue() {
		activeTab = 'queue';
		currentPage = 1;
		await fetchData();
	}

	function ensurePolicyFormProfile() {
		const options = profileOptionsForEngine(policyProfiles, policyForm.engine);
		if (!policyForm.profile_name && options.length > 0) {
			policyForm.profile_name = options[0].name;
		}
	}

	async function fetchPolicyMatrix() {
		policyLoading = true;
		policyError = null;
		try {
			const [policyRes, profilesRes] = await Promise.all([
				llmApi.listScheduleProfilePolicies(),
				llmApi.listProfiles()
			]);
			profilePolicies = policyRes.policies;
			policyProfiles = profilesRes.profiles;
			if (!policyProfiles.some(profile => profile.engine === policyForm.engine)) {
				policyForm.engine = profilesRes.supported_engines[0] || policyProfiles[0]?.engine || policyForm.engine;
				policyForm.profile_name = '';
			}
			ensurePolicyFormProfile();
		} catch (e) {
			policyError = errorMessage(e);
		} finally {
			policyLoading = false;
		}
	}

	async function savePolicyMatrix(nextPolicies: LLMScheduleProfilePolicyItem[]) {
		policySaving = true;
		policyError = null;
		try {
			const saved = await llmApi.updateScheduleProfilePolicies(nextPolicies);
			profilePolicies = saved.policies;
			toast.success('Profile 정책 저장 완료');
		} catch (e) {
			policyError = errorMessage(e);
			toast.error('Profile 정책 저장 실패: ' + errorMessage(e));
		} finally {
			policySaving = false;
		}
	}

	async function addPolicyFromForm() {
		const targetType = policyForm.target_type.trim();
		if (!targetType) {
			policyError = 'target_type을 입력해주세요.';
			return;
		}
		if (!policyForm.profile_name) {
			policyError = 'profile을 선택해주세요.';
			return;
		}
		try {
			const policy: LLMScheduleProfilePolicyItem = {
				target_type: targetType,
				schedule_id: null,
				engine: policyForm.engine,
				profile_name: policyForm.profile_name,
				enabled: policyForm.enabled,
				priority: Number(policyForm.priority) || 0,
				allowed_windows: parsePolicyWindows(policyForm.allowed_windows_text),
				quiet_windows: parsePolicyWindows(policyForm.quiet_windows_text)
			};
			const nextPolicies = [
				...profilePolicies.filter(existing => !(
					(existing.schedule_id || null) === null &&
					(existing.target_type || '') === policy.target_type &&
					existing.engine === policy.engine &&
					existing.profile_name === policy.profile_name
				)),
				policy
			];
			await savePolicyMatrix(nextPolicies);
		} catch (e) {
			policyError = errorMessage(e);
		}
	}

	async function removePolicy(policy: LLMScheduleProfilePolicyItem) {
		const nextPolicies = profilePolicies.filter(existing => existing !== policy);
		await savePolicyMatrix(nextPolicies);
	}

	async function openModal(request: LLMRequest) {
		selectedRequest = request;
		showModal = true;
		editCwd = (request.cli_options?.cwd as string) ?? '';
		try {
			const detail = await llmApi.get(request.id);
			if (showModal && selectedRequest?.id === request.id) {
				selectedRequest = detail;
				editCwd = (detail.cli_options?.cwd as string) ?? editCwd;
			}
		} catch {
			// 상세 조회가 실패해도 목록 데이터로 모달을 유지한다.
		}
		if (request.status === 'pending') {
			try {
				quotaStatus = await llmApi.getQuotaStatus();
				const provider = request.provider || 'claude';
				const providerStatus = quotaStatus[provider];
				if (providerStatus?.paused && providerStatus.remaining_seconds) {
					countdownSeconds = providerStatus.remaining_seconds;
					if (countdownTimer) clearInterval(countdownTimer);
					countdownTimer = setInterval(() => {
						if (countdownSeconds > 0) countdownSeconds--;
					}, 1000);
				}
			} catch {
				// 네트워크 오류 시 배너를 표시하지 않는다.
			}
		}
	}

	function closeModal() {
		showModal = false;
		selectedRequest = null;
		quotaStatus = {};
		countdownSeconds = 0;
		if (countdownTimer) {
			clearInterval(countdownTimer);
			countdownTimer = null;
		}
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

	async function switchTab(tab: LlmTabId) {
		if (activeTab === 'create' && tab !== 'create') {
			const hasContent = createForm.prompt.trim() || createForm.userInput.trim();
			if (hasContent && !await confirm({ title: '탭 전환', message: '작성 중인 내용이 있습니다. 탭을 전환하시겠습니까?', confirmText: '전환' })) {
				return;
			}
		}
		activeTab = tab;
		if (tab === 'queue' || tab === 'history') {
			currentPage = 1;
			selectedIds = [];
			selectAll = false;
			void fetchData();
		}
		if (tab === 'history') {
			void fetchHistoryStats();
		}
		if (tab === 'create') {
			void loadCreateMeta();
		}
		if (tab === 'profilePolicy') {
			void fetchPolicyMatrix();
		}
		if (tab === 'performance') {
			void loadPerformanceTabComponent();
		}
		if (tab === 'claude-sessions') {
			void loadClaudeSessionsTabComponent();
		}
	}

	onMount(() => {
		void fetchData();
	});
</script>

<div class="space-y-4">
	<LlmOverviewPanel
		{stats}
		{workerStatus}
		{queueStats}
		{activeTab}
		onSwitchTab={switchTab}
		onRefresh={fetchData}
		onRunCleanup={runCleanup}
	/>

	<TabNav
		tabs={llmTabs}
		bind:activeTab
		variant="secondary"
		level="secondary"
		size="compact"
		onTabChange={(tabId) => switchTab(tabId as LlmTabId)}
	/>

	{#if activeTab === 'queue' || activeTab === 'history'}
		<LlmRequestsPanel
			activeTab={activeTab}
			{loading}
			{error}
			{stats}
			{requests}
			{callerGroups}
			{groupedResponse}
			{historyStats}
			bind:viewMode
			bind:onlyWithoutSuccess
			bind:filterCallerType
			bind:filterRequestedBy
			bind:filterQueueName
			{selectedIds}
			{selectAll}
			{selectedGroupKeys}
			{groupSelectAll}
			{currentPage}
			{pageSize}
			{total}
			{pages}
			{groupCurrentPage}
			{groupPageSize}
			{groupTotal}
			{groupPages}
			{quotaStatus}
			onFilter={handleFilter}
			onGroupFilter={handleGroupFilter}
			onClearFilters={clearFilters}
			onToggleViewMode={toggleViewMode}
			onRetryAllFailedWithoutSuccess={retryAllFailedWithoutSuccess}
			onMultiRetrySelectedGroups={multiRetrySelectedGroups}
			onToggleGroupSelectAll={toggleGroupSelectAll}
			onToggleGroupSelect={toggleGroupSelect}
			onBatchRetry={batchRetry}
			onBatchDelete={batchDelete}
			onToggleSelectAll={toggleSelectAll}
			onToggleSelect={toggleSelect}
			onOpenRequest={openModal}
			onCancelRequest={cancelRequest}
			onRetryRequest={retryRequest}
			onDeleteRequest={deleteRequest}
			onPrevPage={prevPage}
			onNextPage={nextPage}
			onGroupPrevPage={groupPrevPage}
			onGroupNextPage={groupNextPage}
			onSwitchTab={switchTab}
		/>
	{:else if activeTab === 'create'}
		<LlmCreateRequestPanel
			bind:createForm
			{createLoading}
			{createError}
			bind:createSuccess
			{providers}
			{providersLoading}
			{providersError}
			{presets}
			bind:selectedPreset
			getProviderModels={(providerKey) => getProviderModels(providers, providerKey)}
			onApplyPreset={applyPreset}
			onCreateRequest={createRequest}
			onShowQueue={showCreatedRequestInQueue}
		/>
	{:else if activeTab === 'profilePolicy'}
		<LlmPolicyPanel
			{profilePolicies}
			{policyProfiles}
			{policyLoading}
			{policySaving}
			{policyError}
			bind:policyForm
			onRefresh={fetchPolicyMatrix}
			onAddPolicy={addPolicyFromForm}
			onRemovePolicy={removePolicy}
		/>
	{:else if activeTab === 'performance'}
		{#if performanceTabComponent}
			<svelte:component this={performanceTabComponent} />
		{:else}
			<div class="flex justify-center items-center h-64">
				<div class="text-sm text-muted-foreground">성능 탭 로딩 중...</div>
			</div>
		{/if}
	{:else if activeTab === 'claude-sessions'}
		{#if claudeSessionsTabComponent}
			<svelte:component this={claudeSessionsTabComponent} />
		{:else}
			<div class="flex justify-center items-center h-64">
				<div class="text-sm text-muted-foreground">Claude 세션 탭 로딩 중...</div>
			</div>
		{/if}
	{/if}
</div>

{#if showModal && selectedRequest}
	<LlmRequestDetailModal
		request={selectedRequest}
		{quotaStatus}
		{countdownSeconds}
		bind:editCwd
		{editCwdSaving}
		onClose={closeModal}
		onCancelRequest={cancelRequest}
		onRetryRequest={retryRequest}
		onDeleteRequest={deleteRequest}
		onUpdateCwd={updateCwd}
	/>
{/if}
