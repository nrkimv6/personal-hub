<script lang="ts">
	import { Button } from '$lib/components/ui';
	import TabNav from '$lib/components/layout/TabNav.svelte';

	import { onMount } from 'svelte';
	import { formatLLMBlockReason, llmApi, type LLMBootstrapResponse, type LLMRequest, type LLMStats, type LLMWorkerStatus, type LLMHistoryStats, type LLMQueueStats, type LLMCallerGroup, type LLMGroupedListResponse, type QuotaStatusMap, type ProviderInfo, type LLMProfileConfig, type LLMScheduleProfilePolicyItem, type LLMScheduleProfilePolicyWindow } from '$lib/api';
	import { toast } from '$lib/stores/toast';
	import { confirm } from '$lib/stores/confirm';
	import { fetchQuotaStatus, getQuotaWarning } from '$lib/stores/quotaStore';

	// 상태
	let requests = $state<LLMRequest[]>([]);
	let stats = $state<LLMStats | null>(null);
	let workerStatus = $state<LLMWorkerStatus | null>(null);
	let historyStats = $state<LLMHistoryStats | null>(null);
	let queueStats = $state<LLMQueueStats | null>(null);

	// 그룹 뷰 상태
	let callerGroups = $state<LLMCallerGroup[]>([]);
	let groupedResponse = $state<LLMGroupedListResponse | null>(null);
	let viewMode = $state<'individual' | 'grouped'>('individual');
	let onlyWithoutSuccess = $state(false);

	let loading = $state(true);
	let error = $state<string | null>(null);
	let initialAutoSwitchHandled = false;

	// 페이지네이션
	let currentPage = $state(1);
	const pageSize = 20;
	let total = $state(0);
	let pages = $state(0);

	// 그룹 뷰 페이지네이션
	let groupCurrentPage = $state(1);
	const groupPageSize = 50;
	let groupTotal = $state(0);
	let groupPages = $state(0);

	// 그룹 선택 (multi-재요청용)
	let selectedGroupKeys = $state<string[]>([]);  // "caller_type:caller_id" 형식
	let groupSelectAll = $state(false);

	// 필터 (탭에 따라 다르게 설정)
	let filterCallerType = $state('');
	let filterRequestedBy = $state('');
	let filterQueueName = $state('');  // '' = 전체, 'utility', 'system'

	// 선택
	let selectedIds = $state<number[]>([]);
	let selectAll = $state(false);

	// 탭: queue(대기열), history(이력), create(수동생성), profilePolicy(정책), performance(성능), claude-sessions(세션 뷰어)
	type Tab = 'queue' | 'history' | 'create' | 'profilePolicy' | 'performance' | 'claude-sessions';
	let activeTab = $state<Tab>('queue');
	const llmTabs = [
		{ id: 'queue', label: '대기열', shortLabel: '대기' },
		{ id: 'history', label: '이력', shortLabel: '이력' },
		{ id: 'create', label: '수동 요청 생성', shortLabel: '생성' },
		{ id: 'profilePolicy', label: 'Profile 정책', shortLabel: '정책' },
		{ id: 'performance', label: '성능 분석', shortLabel: '성능' },
		{ id: 'claude-sessions', label: 'Claude 세션', shortLabel: '세션' }
	];

	// 모달
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
		cli_options: undefined as Record<string, unknown> | undefined,
		userInput: ''
	});
	let createLoading = $state(false);
	let createError = $state<string | null>(null);
	let createSuccess = $state(false);

	let profilePolicies = $state<LLMScheduleProfilePolicyItem[]>([]);
	let policyProfiles = $state<LLMProfileConfig[]>([]);
	let policyLoading = $state(false);
	let policySaving = $state(false);
	let policyError = $state<string | null>(null);
	let policyForm = $state({
		target_type: 'plan_archive_analyze',
		engine: 'claude',
		profile_name: '',
		enabled: true,
		priority: 0,
		allowed_windows_text: '',
		quiet_windows_text: ''
	});

	function errorMessage(e: unknown): string {
		return e instanceof Error ? e.message : '알 수 없는 오류';
	}

	function parsePolicyWindows(value: string): LLMScheduleProfilePolicyWindow[] {
		const trimmed = value.trim();
		if (!trimmed) return [];
		if (trimmed.startsWith('[')) {
			return JSON.parse(trimmed) as LLMScheduleProfilePolicyWindow[];
		}
		return trimmed.split(/\r?\n/)
			.map(line => line.trim())
			.filter(Boolean)
			.map(line => {
				const [timeRange, daysPart] = line.split(/\s+/);
				const [start, end] = timeRange.split('-');
				if (!start || !end) {
					throw new Error('window 형식은 HH:MM-HH:MM 입니다');
				}
				const window: LLMScheduleProfilePolicyWindow = { start, end };
				if (daysPart) {
					window.days = daysPart.split(',').map(day => Number(day.trim()));
				}
				return window;
			});
	}

	function formatPolicyWindows(windows: LLMScheduleProfilePolicyWindow[]): string {
		if (!windows.length) return '-';
		return windows.map(window => {
			const days = window.days?.length ? ` ${window.days.join(',')}` : '';
			return `${window.start}-${window.end}${days}`;
		}).join(', ');
	}

	function formatPolicyScope(policy: LLMScheduleProfilePolicyItem): string {
		if (policy.schedule_id) return `schedule #${policy.schedule_id}`;
		return policy.target_type || 'global';
	}

	function getPolicyBlockReasonLabel(reason: string): string {
		return formatLLMBlockReason(reason);
	}

	function profileOptionsForEngine(engine: string): LLMProfileConfig[] {
		return policyProfiles.filter(profile => profile.engine === engine);
	}

	function policyEngines(): string[] {
		const engines = Array.from(new Set(policyProfiles.map(profile => profile.engine)));
		return engines.length > 0 ? engines : [policyForm.engine];
	}

	function ensurePolicyFormProfile() {
		const options = profileOptionsForEngine(policyForm.engine);
		if (!policyForm.profile_name && options.length > 0) {
			policyForm.profile_name = options[0].name;
		}
	}

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

	let selectedPreset = $state<Preset>(presets[0]);
	let userInput = $state('');

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
		createForm.cli_options = preset.cliOptions ?? undefined;
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

			if (shouldAutoSwitchToHistory(bootstrapRes)) {
				initialAutoSwitchHandled = true;
				activeTab = 'history';
				await fetchHistoryStats();
				await fetchData();
				return;
			}

			// 서버에서 이미 status 필터링된 결과 사용
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
		if (!await confirm({ title: '일괄 재시도', message: '성공한 적 없는 모든 caller의 실패 요청을 재시도하시겠습니까?', confirmText: '재시도' })) return;
		try {
			const result = await llmApi.retryFailedCallersWithoutSuccess(filterCallerType || undefined);
			toast.success(`재시도 완료: ${result.retried}개 요청 (${result.callers}개 caller)`);
			await fetchGroupedData();
		} catch (e) {
			toast.error('재시도 실패: ' + errorMessage(e));
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
			toast.error('취소 실패: ' + errorMessage(e));
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
			toast.error('재시도 실패: ' + errorMessage(e));
		}
	}

	async function deleteRequest(id: number) {
		if (!await confirm({ title: '요청 삭제', message: '이 요청을 삭제하시겠습니까?', confirmText: '삭제', variant: 'danger' })) return;
		try {
			await llmApi.delete(id);
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
			const result = await llmApi.batchDelete(selectedIds);
			toast.success(`삭제 완료: ${result.deleted}개`);
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
				cli_options: undefined,
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

	function getPendingPauseInfo(request: LLMRequest): { label: string; title: string; tone: 'quota' | 'window' } | null {
		if (request.status !== 'pending') return null;
		if (request.pending_block_reason) {
			return {
				label: formatLLMBlockReason(request.pending_block_reason),
				title: request.pending_block_reason,
				tone: 'quota'
			};
		}
		const windowPause = quotaStatus.__execution_window;
		if (windowPause?.paused) {
			const wait = windowPause.remaining_seconds != null ? formatWaitTime(windowPause.remaining_seconds) : null;
			return {
				label: '시간창 보류',
				title: wait ? `다음 실행 가능 시간까지 ${wait}` : '현재 실행 가능 시간창 밖입니다',
				tone: 'window'
			};
		}
		const provider = request.provider || 'claude';
		const providerPause = quotaStatus[provider];
		if (providerPause?.paused) {
			const wait = providerPause.remaining_seconds != null ? formatWaitTime(providerPause.remaining_seconds) : null;
			return {
				label: '쿼터 보류',
				title: wait ? `${provider} 쿼터 재개까지 ${wait}` : providerPause.reason || `${provider} 쿼터 일시정지`,
				tone: 'quota'
			};
		}
		return null;
	}

	async function switchTab(tab: Tab) {
		// create 탭에서 작성 중인 내용이 있으면 경고
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
	<div class="flex flex-wrap justify-end gap-2">
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

	<TabNav
		tabs={llmTabs}
		bind:activeTab
		variant="primary"
		size="compact"
		onTabChange={(tabId) => switchTab(tabId as Tab)}
	/>

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
				{#if activeTab === 'queue' && stats && (stats.completed + stats.failed) > 0}
					<div class="mt-3">
						<Button variant="secondary" size="sm" onclick={() => switchTab('history')}>
							이력 보기
						</Button>
					</div>
				{/if}
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
							{@const pauseInfo = getPendingPauseInfo(request)}
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
									{#if pauseInfo}
										<span
											class="ml-1 px-2 py-1 text-xs rounded-full {pauseInfo.tone === 'window' ? 'bg-blue-100 text-blue-700' : 'bg-warning-light text-warning-foreground'}"
											title={pauseInfo.title}
										>
											{pauseInfo.label}
										</span>
									{/if}
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
	{:else if activeTab === 'profilePolicy'}
		<div class="space-y-4">
			<div class="flex items-center justify-between gap-3">
				<div>
					<h3 class="text-base font-semibold text-foreground">Schedule x Profile 정책</h3>
					<p class="text-sm text-muted-foreground">target_type 별로 허용할 profile과 시간대를 지정합니다.</p>
				</div>
				<Button variant="secondary" size="sm" onclick={fetchPolicyMatrix} disabled={policyLoading}>
					{policyLoading ? '로딩 중...' : '새로고침'}
				</Button>
			</div>

			{#if policyError}
				<div class="rounded-lg border border-error/30 bg-error-light px-4 py-3 text-sm text-error">
					{policyError}
				</div>
			{/if}

			<div class="card p-5">
				<div class="grid gap-4 md:grid-cols-5">
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">target_type</label>
						<input type="text" bind:value={policyForm.target_type} class="w-full px-3 py-2 border border-border rounded-lg" />
					</div>
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">Engine</label>
						<select bind:value={policyForm.engine} onchange={() => { policyForm.profile_name = ''; ensurePolicyFormProfile(); }} class="w-full px-3 py-2 border border-border rounded-lg">
							{#each policyEngines() as engine}
								<option value={engine}>{engine}</option>
							{/each}
						</select>
					</div>
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">Profile</label>
						<select bind:value={policyForm.profile_name} class="w-full px-3 py-2 border border-border rounded-lg">
							{#each profileOptionsForEngine(policyForm.engine) as profile}
								<option value={profile.name}>{profile.name}</option>
							{/each}
						</select>
					</div>
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">Priority</label>
						<input type="number" bind:value={policyForm.priority} class="w-full px-3 py-2 border border-border rounded-lg" />
					</div>
					<div class="flex items-end">
						<label class="flex items-center gap-2 text-sm text-foreground">
							<input type="checkbox" bind:checked={policyForm.enabled} class="h-4 w-4" />
							사용
						</label>
					</div>
				</div>

				<div class="mt-4 grid gap-4 md:grid-cols-2">
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">허용 window</label>
						<textarea bind:value={policyForm.allowed_windows_text} rows="3" placeholder="09:00-18:00 1,2,3,4,5" class="w-full px-3 py-2 border border-border rounded-lg resize-none"></textarea>
					</div>
					<div>
						<label class="block text-sm font-medium text-foreground mb-1">차단 window</label>
						<textarea bind:value={policyForm.quiet_windows_text} rows="3" placeholder="00:00-06:00" class="w-full px-3 py-2 border border-border rounded-lg resize-none"></textarea>
					</div>
				</div>

				<div class="mt-4 flex justify-end">
					<Button variant="primary" size="sm" onclick={addPolicyFromForm} disabled={policySaving || policyLoading}>
						{policySaving ? '저장 중...' : '정책 추가/갱신'}
					</Button>
				</div>
			</div>

			<div class="card overflow-hidden">
				<table class="w-full text-sm">
					<thead class="bg-muted/50 text-muted-foreground">
						<tr>
							<th class="px-4 py-3 text-left font-medium">Scope</th>
							<th class="px-4 py-3 text-left font-medium">Engine/Profile</th>
							<th class="px-4 py-3 text-left font-medium">상태</th>
							<th class="px-4 py-3 text-left font-medium">Windows</th>
							<th class="px-4 py-3 text-right font-medium">작업</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#if policyLoading}
							<tr>
								<td colspan="5" class="px-4 py-6 text-center text-muted-foreground">정책 로딩 중...</td>
							</tr>
						{:else if profilePolicies.length === 0}
							<tr>
								<td colspan="5" class="px-4 py-6 text-center text-muted-foreground">등록된 정책이 없습니다.</td>
							</tr>
						{:else}
							{#each profilePolicies as policy}
								<tr>
									<td class="px-4 py-3 font-medium text-foreground">{formatPolicyScope(policy)}</td>
									<td class="px-4 py-3 text-muted-foreground">{policy.engine}/{policy.profile_name}</td>
									<td class="px-4 py-3">
										<span class="rounded-full px-2 py-1 text-xs {policy.enabled ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">
											{policy.enabled ? '사용' : getPolicyBlockReasonLabel('schedule_policy_off')}
										</span>
										<span class="ml-2 text-xs text-muted-foreground">P{policy.priority}</span>
									</td>
									<td class="px-4 py-3 text-muted-foreground">
										<div>허용: {formatPolicyWindows(policy.allowed_windows)}</div>
										<div>차단: {formatPolicyWindows(policy.quiet_windows)}</div>
									</td>
									<td class="px-4 py-3 text-right">
										<Button variant="ghost" size="sm" onclick={() => removePolicy(policy)} disabled={policySaving}>
											삭제
										</Button>
									</td>
								</tr>
							{/each}
						{/if}
					</tbody>
				</table>
			</div>
		</div>
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
					{@const windowPause = quotaStatus.__execution_window}
					{#if windowPause?.paused}
						<div class="mb-4 p-3 bg-blue-50 rounded-lg flex items-start gap-2">
							<span class="text-blue-700 text-sm font-medium">시간창 보류</span>
							<span class="text-blue-700 text-sm ml-auto">
								{windowPause.remaining_seconds != null ? `${formatWaitTime(windowPause.remaining_seconds)} 후 재개` : '다음 시간창 대기'}
							</span>
						</div>
					{:else if ps?.paused}
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
