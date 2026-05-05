<script lang="ts">
	import { Button } from '$lib/components/ui';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';

	import { onMount } from 'svelte';
	import { collectApi, llmApi, type ProviderInfo } from '$lib/api';
	import type { CrawlSchedule, ServiceAccountWithProfile, CrawlScheduleRepairResponse } from '$lib/types';
	import InstagramCrawlSettings from '$lib/components/InstagramCrawlSettings.svelte';
	import {
		Instagram,
		Search,
		Pencil,
		FlaskConical,
		FolderArchive,
		ClipboardList,
		Moon,
		ArrowLeft,
		X,
		ChevronDown,
		ChevronRight,
		Clock,
		BarChart3,
		Trash2,
		Plus
	} from 'lucide-svelte';

	let schedules: CrawlSchedule[] = [];
	let loading = true;
	let error: string | null = null;
	let successMessage: string | null = null;

	let togglingId: number | null = null;
	let runningId: number | null = null;

	// Instagram 설정 모달 상태
	let showInstagramSettingsModal = false;
	let instagramSettingsSchedule: CrawlSchedule | null = null;
	let settingsRef: InstagramCrawlSettings | null = null;

	// 추가 모달 상태
	let showAddModal = false;
	let addStep = 1; // 1: 타입 선택, 2: 대상 선택, 3: 시간 설정
	let creating = false;

	// 선택값
	let selectedType = ''; // 'instagram_feed' | 'google_search' | 'writing_task'
	let selectedTarget: { id: number; name: string } | null = null;
	let scheduleTimes: string[] = ['09:00', '12:00', '18:00'];

	// pytest_run 설정
	let pytestTestPath = 'tests/';
	let pytestExtraArgs = '';
	let pytestAutoFixPlan = true;
	let pytestLlmUseSystemDefaults = true;
	let providers = $state<ProviderInfo[]>([]);
	let pytestLlmProvider = 'claude';
	let pytestLlmModel = '';
	let pytestCronTime = '02:00';

	// plan_archive_analyze / devguide_staleness / auto_dev_runner cron 시간
	let planArchiveCronTime = '02:10';
	let devguideStaleCronTime = '03:30';
	let autoDevRunnerCronTime = '02:00';

	// 수정 모달 cron 시간 (pytest / plan 타입 공용)
	let editCronTime = '02:00';

	// Google 검색 새 검색어 입력 폼
	let newSearchQuery = '';
	let newSearchName = '';
	let newSearchDateFilter = '';
	let newSearchMaxPages = 1;
	let newSearchLr = '';
	let newSearchCr = '';
	let newSearchSitesearch = '';
	let showAdvancedOptions = false;

	// 대상 목록
	let serviceAccounts: ServiceAccountWithProfile[] = [];
	let loadingTargets = false;

	// 삭제 모달 상태
	let showDeleteModal = false;
	let deleteTarget: CrawlSchedule | null = null;
	let deleting = false;

	// 수정 모달 상태
	let showEditModal = false;
	let editSchedule: CrawlSchedule | null = null;
	let editLoading = false;
	let editSaving = false;
	let editDisplayName = '';
	let editTimes: string[] = [];
	// Google 검색 수정 전용
	let editGoogleQuery = '';
	let editGoogleName = '';
	let editGoogleDateFilter = '';
	let editGoogleMaxPages = 1;
	let editGoogleLr = '';
	let editGoogleCr = '';
	let editGoogleSitesearch = '';
	let editShowAdvanced = false;
	// LLM 설정 (instagram_feed, writing_task, topic_extract 전용)
	let editLlmUseSystemDefaults = true;
	let editLlmProvider = 'claude';
	let editLlmModel = '';
	let showLegacyRepairModal = false;
	let legacyRepairPreview: CrawlScheduleRepairResponse | null = null;
	let loadingLegacyRepair = false;
	let applyingLegacyRepair = false;

	const LLM_TARGET_TYPES = ['instagram_feed', 'writing_task', 'topic_extract', 'pytest_run', 'plan_archive_analyze'];

	const scheduleTypes = [
		{ value: 'instagram_feed', label: 'Instagram 피드', icon: Instagram, color: 'pink' },
		{ value: 'google_search', label: 'Google 검색', icon: Search, color: 'yellow' },
		{ value: 'writing_task', label: '글쓰기 태스크', icon: Pencil, color: 'purple' },
		{ value: 'pytest_run', label: 'pytest 자동 실행', icon: FlaskConical, color: 'green' },
		{ value: 'plan_archive_analyze', label: 'Plan Archive LLM 분석', icon: FolderArchive, color: 'blue' },
		{ value: 'devguide_staleness', label: 'Dev-Guide 갱신 점검', icon: ClipboardList, color: 'indigo' },
		{ value: 'auto_dev_runner', label: '야간 자동 plan 실행', icon: Moon, color: 'purple' }
	];

	const dateFilterOptions = [
		{ value: '', label: '전체 기간' },
		{ value: '1h', label: '1시간 이내' },
		{ value: '24h', label: '24시간 이내' },
		{ value: '1w', label: '1주일 이내' },
		{ value: '1m', label: '1개월 이내' },
		{ value: '1y', label: '1년 이내' }
	];

	const languageOptions = [
		{ value: '', label: '제한 없음' },
		{ value: 'lang_ko', label: '한국어' },
		{ value: 'lang_en', label: '영어' },
		{ value: 'lang_ja', label: '일본어' }
	];

	const countryOptions = [
		{ value: '', label: '제한 없음' },
		{ value: 'countryKR', label: '한국' },
		{ value: 'countryUS', label: '미국' },
		{ value: 'countryJP', label: '일본' }
	];

	// ============ Instagram 설정 모달 ============

	function openInstagramSettings(schedule: CrawlSchedule) {
		instagramSettingsSchedule = schedule;
		showInstagramSettingsModal = true;
	}

	function closeInstagramSettings() {
		showInstagramSettingsModal = false;
		instagramSettingsSchedule = null;
		fetchSchedules();
	}

	// ============ 추가 모달 ============

	function openAddModal() {
		showAddModal = true;
		addStep = 1;
		selectedType = '';
		selectedTarget = null;
		scheduleTimes = ['09:00', '12:00', '18:00'];
		pytestLlmUseSystemDefaults = true;
		resetNewSearchForm();
	}

	function closeAddModal() {
		showAddModal = false;
		addStep = 1;
		selectedType = '';
		selectedTarget = null;
	}

	function resetNewSearchForm() {
		newSearchQuery = '';
		newSearchName = '';
		newSearchDateFilter = '';
		newSearchMaxPages = 1;
		newSearchLr = '';
		newSearchCr = '';
		newSearchSitesearch = '';
		showAdvancedOptions = false;
	}

	async function selectType(type: string) {
		selectedType = type;

		if (type === 'writing_task') {
			addStep = 3;
			return;
		}

		if (type === 'pytest_run') {
			// pytest_run은 설정 폼(step 2)으로 이동
			addStep = 2;
			return;
		}

		if (type === 'plan_archive_analyze' || type === 'devguide_staleness' || type === 'auto_dev_runner') {
			// cron 시간만 입력 (step 2)
			addStep = 2;
			return;
		}

		if (type === 'google_search') {
			// Google 검색은 항상 새 검색어 입력 폼으로 이동
			addStep = 2;
			return;
		}

		loadingTargets = true;
		try {
			if (type === 'instagram_feed') {
				serviceAccounts = await collectApi.getAccounts();
			}
			addStep = 2;
		} catch (e) {
			error = e instanceof Error ? e.message : '대상 목록 로드 실패';
		} finally {
			loadingTargets = false;
		}
	}

	function selectTarget(target: { id: number; name: string }) {
		selectedTarget = target;
		addStep = 3;
	}

	function proceedWithNewSearch() {
		if (!newSearchQuery.trim()) {
			error = '검색 키워드를 입력해주세요';
			return;
		}
		selectedTarget = null; // 새 검색어는 target 없음
		addStep = 3;
	}

	function addTime() {
		scheduleTimes = [...scheduleTimes, '12:00'];
	}

	function removeTime(index: number) {
		scheduleTimes = scheduleTimes.filter((_, i) => i !== index);
	}

	async function createSchedule() {
		if (!selectedType) return;

		creating = true;
		error = null;

		try {
			const isCronType = selectedType === 'pytest_run' || selectedType === 'plan_archive_analyze' || selectedType === 'devguide_staleness' || selectedType === 'auto_dev_runner';
		const cronTime =
			selectedType === 'pytest_run' ? pytestCronTime :
			selectedType === 'plan_archive_analyze' ? planArchiveCronTime :
			selectedType === 'devguide_staleness' ? devguideStaleCronTime :
			selectedType === 'auto_dev_runner' ? autoDevRunnerCronTime : '';

		const data: {
				target_type: string;
				target_config?: Record<string, unknown>;
				schedule_type: string;
				schedule_value: Record<string, unknown>;
			} = {
				target_type: selectedType,
				schedule_type: isCronType ? 'cron' : 'time_window',
				schedule_value:
					isCronType
						? { time: cronTime }
						: {
								daily_runs: scheduleTimes.length,
								time_windows: scheduleTimes.map((t) => ({ start: t, end: t }))
							}
			};

			if (selectedType === 'pytest_run') {
				const extraArgsList = pytestExtraArgs
					.split(/\s+/)
					.map((s) => s.trim())
					.filter(Boolean);
				const pytestTargetConfig: Record<string, unknown> = {
					test_path: pytestTestPath.trim() || 'tests/',
					extra_args: extraArgsList,
					auto_fix_plan: pytestAutoFixPlan
				};
				if (!pytestLlmUseSystemDefaults) {
					pytestTargetConfig.llm_provider = pytestLlmProvider;
					pytestTargetConfig.llm_model = pytestLlmModel.trim();
				}
				data.target_config = pytestTargetConfig;
			} else if (selectedType === 'instagram_feed' && selectedTarget) {
				data.target_config = { service_account_id: selectedTarget.id };
			} else if (selectedType === 'google_search') {
				const searchParams: Record<string, unknown> = {};
				if (newSearchLr) searchParams.lr = newSearchLr;
				if (newSearchCr) searchParams.cr = newSearchCr;
				if (newSearchSitesearch) searchParams.as_sitesearch = newSearchSitesearch;

				data.target_config = {
					create_new_search: true,
					query: newSearchQuery.trim(),
					name: newSearchName.trim() || undefined,
					date_filter: newSearchDateFilter || undefined,
					max_pages: newSearchMaxPages,
					search_params: Object.keys(searchParams).length > 0 ? searchParams : undefined
				};
			}

			await collectApi.createSchedule(data);
			successMessage = '스케줄이 생성되었습니다';
			closeAddModal();
			await fetchSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 생성 실패';
		} finally {
			creating = false;
		}
	}

	// ============ 수정 모달 ============

	async function openEditModal(schedule: CrawlSchedule) {
		editSchedule = schedule;
		editLoading = true;
		showEditModal = true;
		editShowAdvanced = false;
		error = null;

		try {
			const detail = await collectApi.getScheduleDetail(schedule.id);

			editDisplayName = detail.display_name || '';

			// cron 타입 (pytest_run, plan_archive_analyze, devguide_staleness, auto_dev_runner) cron 시간 복원
			const isCronSchedule = ['pytest_run', 'plan_archive_analyze', 'devguide_staleness', 'auto_dev_runner'].includes(schedule.target_type);
			if (isCronSchedule && detail.schedule_value?.time) {
				editCronTime = detail.schedule_value.time as string;
			} else {
				editCronTime = '02:00';
			}

			// 시간 설정 복원
			if (detail.schedule_value?.time_windows) {
				editTimes = (detail.schedule_value.time_windows as { start: string; end: string }[]).map(
					(tw) => tw.start
				);
			} else {
				editTimes = ['09:00'];
			}

			// Google 검색 파라미터 복원
			if (schedule.target_type === 'google_search' && detail.saved_search) {
				editGoogleQuery = detail.saved_search.query || '';
				editGoogleName = detail.saved_search.name || '';
				editGoogleDateFilter = detail.saved_search.date_filter || '';
				editGoogleMaxPages = detail.saved_search.max_pages || 1;
				const sp = detail.saved_search.search_params as Record<string, string> | null;
				editGoogleLr = sp?.lr || '';
				editGoogleCr = sp?.cr || '';
				editGoogleSitesearch = sp?.as_sitesearch || '';
			} else {
				editGoogleQuery = '';
				editGoogleName = '';
				editGoogleDateFilter = '';
				editGoogleMaxPages = 1;
				editGoogleLr = '';
				editGoogleCr = '';
				editGoogleSitesearch = '';
			}

			// LLM 설정 복원 (instagram_feed, writing_task, topic_extract, pytest_run)
			if (LLM_TARGET_TYPES.includes(schedule.target_type) && detail.target_config) {
				const tc = detail.target_config as Record<string, string>;
				const hasLlmProvider = Object.prototype.hasOwnProperty.call(tc, 'llm_provider');
				const hasLlmModel = Object.prototype.hasOwnProperty.call(tc, 'llm_model');
				editLlmUseSystemDefaults = !(hasLlmProvider || hasLlmModel);
				editLlmProvider = tc.llm_provider || 'claude';
				editLlmModel = tc.llm_model || '';
			} else {
				editLlmUseSystemDefaults = true;
				editLlmProvider = 'claude';
				editLlmModel = '';
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 정보 로드 실패';
			showEditModal = false;
		} finally {
			editLoading = false;
		}
	}

	function closeEditModal() {
		showEditModal = false;
		editSchedule = null;
	}

	async function saveEdit() {
		if (!editSchedule) return;

		editSaving = true;
		error = null;

		try {
			const updateData: {
				display_name?: string;
				schedule_value?: Record<string, unknown>;
				google_search_params?: Record<string, unknown>;
				target_config?: Record<string, unknown> | null;
			} = {};

			// 표시 이름
			if (editDisplayName.trim()) {
				updateData.display_name = editDisplayName.trim();
			}

			// 시간 설정 (cron 타입 vs time_window 타입)
			const isEditCronType = ['pytest_run', 'plan_archive_analyze', 'devguide_staleness', 'auto_dev_runner'].includes(editSchedule.target_type);
			updateData.schedule_value = isEditCronType
				? { time: editCronTime }
				: {
						daily_runs: editTimes.length,
						time_windows: editTimes.map((t) => ({ start: t, end: t }))
					};

			// Google 검색 파라미터
			if (editSchedule.target_type === 'google_search') {
				const searchParams: Record<string, unknown> = {};
				if (editGoogleLr) searchParams.lr = editGoogleLr;
				if (editGoogleCr) searchParams.cr = editGoogleCr;
				if (editGoogleSitesearch) searchParams.as_sitesearch = editGoogleSitesearch;

				updateData.google_search_params = {
					query: editGoogleQuery.trim(),
					name: editGoogleName.trim() || undefined,
					date_filter: editGoogleDateFilter || null,
					max_pages: editGoogleMaxPages,
					search_params: Object.keys(searchParams).length > 0 ? searchParams : {}
				};
			}

			// LLM 설정 (instagram_feed, writing_task, topic_extract, pytest_run)
			if (LLM_TARGET_TYPES.includes(editSchedule.target_type)) {
				updateData.target_config = editLlmUseSystemDefaults
					? { llm_provider: null, llm_model: null }
					: {
							llm_provider: editLlmProvider,
							llm_model: editLlmModel || null
						};
			}

			await collectApi.updateSchedule(editSchedule.id, updateData);
			successMessage = '스케줄이 수정되었습니다';
			closeEditModal();
			await fetchSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 수정 실패';
		} finally {
			editSaving = false;
		}
	}

	function editAddTime() {
		editTimes = [...editTimes, '12:00'];
	}

	function editRemoveTime(index: number) {
		editTimes = editTimes.filter((_, i) => i !== index);
	}

	// ============ 기본 기능 ============

	async function fetchSchedules() {
		loading = true;
		error = null;
		try {
			schedules = await collectApi.getSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function toggleSchedule(schedule: CrawlSchedule) {
		togglingId = schedule.id;
		successMessage = null;
		error = null;
		try {
			const result = await collectApi.toggleSchedule(schedule.id, !schedule.enabled);
			if (result.success) {
				successMessage = `${schedule.display_name || schedule.name}: ${result.enabled ? '활성화' : '비활성화'}됨`;
				await fetchSchedules();
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 토글 실패';
		} finally {
			togglingId = null;
		}
	}

	async function runSchedule(schedule: CrawlSchedule) {
		runningId = schedule.id;
		successMessage = null;
		error = null;
		try {
			const result = await collectApi.runSchedule(schedule.id);
			if (result.success) {
				successMessage = result.message;
			} else {
				error = result.message;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '즉시 실행 실패';
		} finally {
			runningId = null;
		}
	}

	function openDeleteModal(schedule: CrawlSchedule) {
		deleteTarget = schedule;
		showDeleteModal = true;
	}

	function closeDeleteModal() {
		showDeleteModal = false;
		deleteTarget = null;
	}

	async function confirmDelete() {
		if (!deleteTarget) return;

		deleting = true;
		error = null;
		try {
			const result = await collectApi.deleteSchedule(deleteTarget.id, true);
			if (result.success) {
				successMessage = result.message;
				closeDeleteModal();
				await fetchSchedules();
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '삭제 실패';
		} finally {
			deleting = false;
		}
	}

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function getTargetTypeBadge(type: string): { class: string; text: string } {
		switch (type) {
			case 'instagram_feed':
				return { class: 'bg-pink-light text-pink', text: 'Instagram' };
			case 'universal_crawl':
				return { class: 'bg-primary-light text-primary', text: 'Web' };
			case 'google_search':
				return { class: 'bg-warning-light text-warning-foreground', text: 'Google' };
			case 'writing_task':
				return { class: 'bg-purple-light text-purple-800', text: '글쓰기' };
			case 'pytest_run':
				return { class: 'bg-green-100 text-green-800', text: 'pytest' };
			case 'plan_archive_analyze':
				return { class: 'bg-blue-100 text-blue-800', text: 'Plan분석' };
			case 'devguide_staleness':
				return { class: 'bg-indigo-100 text-indigo-800', text: 'Dev-Guide점검' };
			case 'auto_dev_runner':
				return { class: 'bg-purple-100 text-purple-800', text: '야간자동실행' };
			default:
				return { class: 'bg-muted text-foreground', text: type };
		}
	}

	function getScheduleTypeBadge(type: string): { class: string; text: string } {
		switch (type) {
			case 'daily':
				return { class: 'bg-success-light text-success', text: '일일' };
			case 'interval':
				return { class: 'bg-primary-light text-primary', text: '간격' };
			case 'cron':
				return { class: 'bg-purple-light text-purple', text: 'Cron' };
			case 'time_window':
				return { class: 'bg-warning-light text-warning', text: '시간대' };
			default:
				return { class: 'bg-background text-foreground', text: type };
		}
	}

	function getResolutionBadge(schedule: CrawlSchedule): { class: string; text: string } {
		switch (schedule.resolution_source) {
			case 'schedule_pin':
				return { class: 'bg-emerald-100 text-emerald-800', text: 'pin' };
			case 'caller_default':
				return { class: 'bg-blue-100 text-blue-800', text: 'caller default' };
			case 'legacy_placeholder':
				return { class: 'bg-amber-100 text-amber-800', text: 'legacy placeholder' };
			default:
				return { class: 'bg-slate-100 text-slate-700', text: 'inherit' };
		}
	}

	async function previewLegacyRepair() {
		loadingLegacyRepair = true;
		error = null;
		try {
			legacyRepairPreview = await collectApi.previewLegacyPlaceholderRepair();
			showLegacyRepairModal = true;
		} catch (e) {
			error = e instanceof Error ? e.message : 'legacy 복구 미리보기 실패';
		} finally {
			loadingLegacyRepair = false;
		}
	}

	function closeLegacyRepairModal() {
		showLegacyRepairModal = false;
	}

	async function applyLegacyRepair() {
		if (!legacyRepairPreview || legacyRepairPreview.candidate_count === 0) return;
		applyingLegacyRepair = true;
		error = null;
		try {
			await collectApi.applyLegacyPlaceholderRepair();
			successMessage = 'legacy placeholder 복구가 적용되었습니다';
			showLegacyRepairModal = false;
			await fetchSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : 'legacy 복구 적용 실패';
		} finally {
			applyingLegacyRepair = false;
		}
	}

	onMount(() => {
		fetchSchedules();
		llmApi.getProviders().then(data => { providers = data; }).catch(() => {});
	});
</script>

<div>
	<!-- 헤더 -->
	<PageHeader title="스케줄 설정">
		<Button variant="secondary" onclick={previewLegacyRepair} disabled={loadingLegacyRepair}>
			{loadingLegacyRepair ? '복구 조회 중...' : 'legacy 복구'}
		</Button>
		<Button variant="primary" onclick={openAddModal}>
			<Plus size={18} class="mr-1" /> 스케줄 추가
		</Button>
	</PageHeader>

	{#if successMessage}
		<div class="bg-success-light border border-green-200 text-success px-4 py-3 rounded-lg mb-4">
			{successMessage}
		</div>
	{/if}

	{#if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg mb-4">
			{error}
		</div>
	{/if}

	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if schedules.length === 0}
		<div class="card text-center py-12">
			<p class="text-muted-foreground">등록된 스케줄이 없습니다</p>
		</div>
	{:else}
		<div class="space-y-4">
			{#each schedules as schedule}
				{@const targetBadge = getTargetTypeBadge(schedule.target_type)}
				{@const scheduleBadge = getScheduleTypeBadge(schedule.schedule_type)}
				{@const resolutionBadge = getResolutionBadge(schedule)}
				<div class="card">
					<div class="flex items-center justify-between">
						<!-- 스케줄 정보 -->
						<div class="flex items-center gap-4">
							<!-- 활성화 토글 -->
							<button
								onclick={() => toggleSchedule(schedule)}
								disabled={togglingId === schedule.id}
								class="relative inline-flex items-center h-6 rounded-full w-11 transition-colors {schedule.enabled
									? 'bg-primary'
									: 'bg-secondary'}"
							>
								<span
									class="inline-block w-4 h-4 transform bg-white rounded-full transition-transform {schedule.enabled
										? 'translate-x-6'
										: 'translate-x-1'}"
								></span>
							</button>

							<div>
								<div class="flex items-center gap-2">
									<span class="font-medium text-foreground">
										{schedule.display_name || schedule.name}
									</span>
									<span class="px-2 py-0.5 text-xs rounded-full {targetBadge.class}">
										{targetBadge.text}
									</span>
									<span class="px-2 py-0.5 text-xs rounded-full {scheduleBadge.class}">
										{scheduleBadge.text}
									</span>
									<span class="px-2 py-0.5 text-xs rounded-full {resolutionBadge.class}">
										{resolutionBadge.text}
									</span>
								</div>
								<div class="text-sm text-muted-foreground mt-1 flex gap-4">
									<span>마지막 실행: {formatDateTime(schedule.last_run_at)}</span>
									{#if schedule.enabled && schedule.next_run_at}
										<span>다음 실행: {formatDateTime(schedule.next_run_at)}</span>
									{/if}
								</div>
								{#if schedule.resolved_provider}
									<div class="text-xs text-muted-foreground mt-1">
										해석: {schedule.resolved_provider}{#if schedule.resolved_model} / {schedule.resolved_model}{/if}
										{#if schedule.legacy_placeholder_candidate}
											<span class="ml-2 text-amber-700">legacy 후보</span>
										{/if}
									</div>
								{/if}
							</div>
						</div>

						<!-- 버튼 그룹 -->
						<div class="flex items-center gap-2">
							<!-- 실행 이력 버튼 -->
							<a
								href="/crawl/schedules/{schedule.id}/runs"
								class="btn btn-secondary btn-sm flex items-center gap-1"
								title="실행 이력 보기"
							>
								<BarChart3 size={14} /> 이력
							</a>

							<!-- 수정 버튼 (모든 타입) -->
							<Button variant="secondary" size="sm" onclick={() => openEditModal(schedule)}
								title="스케줄 수정"
							>
								<Pencil size={14} /> 수정
							</Button>

							<!-- Instagram 상세 설정 버튼 -->
							{#if schedule.target_type === 'instagram_feed'}
								<Button variant="secondary" size="sm" onclick={() => openInstagramSettings(schedule)}
									title="Instagram 상세 설정"
								>
									IG설정
								</Button>
							{/if}

							<!-- pytest_run 결과 보기 버튼 -->
							{#if schedule.target_type === 'pytest_run'}
								<a
									href="/collect/test-runs"
									class="btn btn-secondary btn-sm flex items-center gap-1"
									title="테스트 실행 결과 보기"
								>
									<FlaskConical size={14} /> 결과
								</a>
							{/if}

							<!-- 즉시 실행 버튼 -->
							<Button
								variant="primary"
								size="sm"
								onclick={() => runSchedule(schedule)}
								disabled={runningId === schedule.id || !schedule.enabled}
								title={!schedule.enabled ? '스케줄을 먼저 활성화하세요' : '즉시 실행'}
							>
								{#if runningId === schedule.id}
									실행 중...
								{:else}
									즉시 실행
								{/if}
							</Button>

							<!-- 삭제 버튼 -->
							<button
								onclick={() => openDeleteModal(schedule)}
								class="btn btn-sm text-error hover:bg-error-light border border-red-200 flex items-center gap-1"
								title="스케줄 삭제"
							>
								<Trash2 size={14} /> 삭제
							</button>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

{#if showLegacyRepairModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
		<div class="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl">
			<div class="flex items-center justify-between border-b border-border px-6 py-4">
				<h2 class="text-lg font-bold text-foreground">legacy placeholder 복구 미리보기</h2>
				<button onclick={closeLegacyRepairModal} class="text-2xl leading-none text-muted-foreground">&times;</button>
			</div>
			<div class="max-h-[calc(90vh-80px)] space-y-4 overflow-y-auto p-6">
				<p class="text-sm text-muted-foreground">
					`llm_provider=claude` + 빈 model 조합만 후보로 잡습니다. apply는 이 키를 제거해 inherit 상태로 되돌립니다.
				</p>
				<div class="grid gap-3 sm:grid-cols-3">
					<div class="rounded border border-border bg-muted/30 p-3">
						<div class="text-xs text-muted-foreground">후보 수</div>
						<div class="mt-1 text-lg font-semibold">{legacyRepairPreview?.candidate_count ?? 0}</div>
					</div>
					<div class="rounded border border-border bg-muted/30 p-3">
						<div class="text-xs text-muted-foreground">적용 대상</div>
						<div class="mt-1 text-lg font-semibold">{legacyRepairPreview?.items.length ?? 0}</div>
					</div>
					<div class="rounded border border-border bg-muted/30 p-3">
						<div class="text-xs text-muted-foreground">적용 모드</div>
						<div class="mt-1 text-lg font-semibold">{legacyRepairPreview?.dry_run ? 'dry-run' : 'apply'}</div>
					</div>
				</div>
				{#if legacyRepairPreview?.items.length}
					<div class="space-y-2">
						{#each legacyRepairPreview.items as item}
							<div class="rounded border border-border p-3">
								<div class="text-sm font-semibold text-foreground">{item.display_name || item.name}</div>
								<div class="mt-1 text-xs text-muted-foreground">{item.target_type} / #{item.id}</div>
								<div class="mt-2 grid gap-2 sm:grid-cols-2">
									<pre class="overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(item.before, null, 2)}</pre>
									<pre class="overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(item.after, null, 2)}</pre>
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-sm text-muted-foreground">적용할 후보가 없습니다.</p>
				{/if}
			</div>
			<div class="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
				<Button variant="secondary" onclick={closeLegacyRepairModal}>닫기</Button>
				<Button variant="primary" onclick={applyLegacyRepair} disabled={applyingLegacyRepair || !legacyRepairPreview?.candidate_count}>
					{applyingLegacyRepair ? '적용 중...' : '복구 적용'}
				</Button>
			</div>
		</div>
	</div>
{/if}

<!-- Instagram 설정 모달 -->
{#if showInstagramSettingsModal && instagramSettingsSchedule?.target_type === 'instagram_feed'}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<h2 class="text-xl font-bold text-foreground">Instagram 수집 설정</h2>
				<button
					onclick={closeInstagramSettings}
					class="text-muted-foreground hover:text-muted-foreground text-2xl leading-none"
				>
					&times;
				</button>
			</div>
			<div class="p-6 overflow-y-auto max-h-[calc(90vh-80px)]">
				<InstagramCrawlSettings bind:this={settingsRef} />
			</div>
		</div>
	</div>
{/if}

<!-- 스케줄 추가 모달 -->
{#if showAddModal}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-hidden">
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<div class="flex items-center gap-2">
					<h2 class="text-xl font-bold text-foreground">스케줄 추가</h2>
					{#if addStep > 1}
						<button
							onclick={() => {
								if (addStep === 3 && selectedType === 'writing_task') {
									addStep = 1;
								} else {
									addStep = addStep - 1;
								}
							}}
							class="text-sm text-primary hover:text-primary-hover flex items-center gap-1"
						>
							<ArrowLeft size={14} /> 이전
						</button>
					{/if}
				</div>
				<button
					onclick={closeAddModal}
					class="text-muted-foreground hover:text-muted-foreground text-2xl leading-none"
				>
					&times;
				</button>
			</div>

			<div class="p-6 overflow-y-auto max-h-[calc(90vh-80px)]">
				{#if addStep === 1}
					<!-- Step 1: 타입 선택 -->
					<p class="text-muted-foreground mb-4">어떤 종류의 스케줄을 추가하시겠습니까?</p>
					<div class="grid grid-cols-1 gap-3">
						{#each scheduleTypes as st}
							<button
								onclick={() => selectType(st.value)}
								disabled={loadingTargets}
								class="flex items-center gap-3 p-4 border-2 rounded-lg hover:border-blue-500 hover:bg-primary-light transition-colors text-left"
							>
								<span class="text-primary">
									<svelte:component this={st.icon} size={24} />
								</span>
								<div>
									<div class="font-medium text-foreground">{st.label}</div>
									<div class="text-sm text-muted-foreground">
										{#if st.value === 'instagram_feed'}
											Instagram 피드를 주기적으로 수집합니다
										{:else if st.value === 'google_search'}
											Google 검색 결과를 주기적으로 수집합니다
										{:else if st.value === 'pytest_run'}
											테스트를 매일 자동 실행하고 실패 시 수정계획 생성
										{:else}
											글쓰기 태스크를 주기적으로 실행합니다
										{/if}
									</div>
								</div>
							</button>
						{/each}
					</div>

				{:else if addStep === 2}
					<!-- Step 2: 대상 선택 -->
					{#if loadingTargets}
						<div class="flex justify-center py-8">
							<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
						</div>
					{:else if selectedType === 'pytest_run'}
						<!-- pytest_run 설정 폼 -->
						<p class="text-muted-foreground mb-4">pytest 실행 설정을 입력하세요</p>
						<div class="space-y-4">
							<div>
								<label for="pytest-path" class="block text-sm font-medium text-foreground mb-1">테스트 경로</label>
								<input
									id="pytest-path"
									type="text"
									bind:value={pytestTestPath}
									placeholder="예: tests/"
									class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring font-mono text-sm"
								/>
								<p class="text-xs text-muted-foreground mt-1">pytest가 실행할 경로 또는 파일</p>
							</div>

							<div>
								<label for="pytest-args" class="block text-sm font-medium text-foreground mb-1">추가 인자</label>
								<input
									id="pytest-args"
									type="text"
									bind:value={pytestExtraArgs}
									placeholder="예: -k test_api --ignore=tests/e2e"
									class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring font-mono text-sm"
								/>
							</div>

							<div>
								<label for="pytest-cron" class="block text-sm font-medium text-foreground mb-1">실행 시각 (매일)</label>
								<input
									id="pytest-cron"
									type="time"
									bind:value={pytestCronTime}
									class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
								/>
								<p class="text-xs text-muted-foreground mt-1">매일 1회 실행 (±5분 허용)</p>
							</div>

							<div class="border-t border-border pt-4">
								<h4 class="text-sm font-medium text-foreground mb-3">실패 시 자동 수정계획 생성</h4>
								<div class="flex items-center gap-3 mb-3">
									<button
										onclick={() => (pytestAutoFixPlan = !pytestAutoFixPlan)}
										class="relative inline-flex items-center h-6 rounded-full w-11 transition-colors {pytestAutoFixPlan ? 'bg-primary' : 'bg-secondary'}"
									>
										<span
											class="inline-block w-4 h-4 transform bg-white rounded-full transition-transform {pytestAutoFixPlan ? 'translate-x-6' : 'translate-x-1'}"
										></span>
									</button>
									<span class="text-sm text-foreground">
										{pytestAutoFixPlan ? 'LLM 수정계획 자동 생성' : '수정계획 생성 안 함'}
									</span>
								</div>

								{#if pytestAutoFixPlan}
									<div class="space-y-3 pl-1">
										<label class="flex items-center gap-3 text-sm text-foreground">
											<input
												type="checkbox"
												bind:checked={pytestLlmUseSystemDefaults}
												class="rounded border-border text-primary focus:ring-ring"
											/>
											<span>시스템 기본값 사용</span>
										</label>
										<div>
											<label for="pytest-provider" class="block text-sm font-medium text-foreground mb-1">LLM Provider</label>
											<select
												id="pytest-provider"
												bind:value={pytestLlmProvider}
												disabled={pytestLlmUseSystemDefaults}
												class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring text-sm"
											>
												{#if providers.length > 0}
													{#each providers as p}
														<option value={p.key}>{p.display_name}</option>
													{/each}
												{:else}
													<option value="claude">Claude</option>
													<option value="gemini">Gemini</option>
												{/if}
											</select>
										</div>
										<div>
											<label for="pytest-model" class="block text-sm font-medium text-foreground mb-1">모델명</label>
											<input
												id="pytest-model"
												type="text"
												bind:value={pytestLlmModel}
												disabled={pytestLlmUseSystemDefaults}
												placeholder="비워두면 기본 모델 사용"
												class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring text-sm"
											/>
										</div>
										{#if pytestLlmUseSystemDefaults}
											<p class="text-xs text-muted-foreground">
												LLM 수정계획은 시스템 기본값과 caller defaults를 따릅니다.
											</p>
										{/if}
									</div>
								{/if}
							</div>

							<div class="flex justify-end">
								<button
									onclick={createSchedule}
									disabled={creating}
									class="btn btn-primary"
								>
									{#if creating}생성 중...{:else}생성{/if}
								</button>
							</div>
						</div>
					{:else if selectedType === 'plan_archive_analyze' || selectedType === 'devguide_staleness' || selectedType === 'auto_dev_runner'}
				<!-- plan archive / devguide_staleness / auto_dev_runner: cron 시간만 입력 -->
				<p class="text-muted-foreground mb-4">매일 실행할 시각을 설정하세요</p>
				<div class="space-y-4">
					<div>
						<label for="plan-cron-time" class="block text-sm font-medium text-foreground mb-1">실행 시각 (매일)</label>
						{#if selectedType === 'plan_archive_analyze'}
							<input
								id="plan-cron-time"
								type="time"
								bind:value={planArchiveCronTime}
								class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							/>
						{:else if selectedType === 'devguide_staleness'}
							<input
								id="plan-cron-time"
								type="time"
								bind:value={devguideStaleCronTime}
								class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							/>
						{:else}
							<input
								id="plan-cron-time"
								type="time"
								bind:value={autoDevRunnerCronTime}
								class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							/>
						{/if}
						<p class="text-xs text-muted-foreground mt-1">매일 1회 실행 (±5분 허용)</p>
					</div>
					<div class="flex justify-end">
						<button
							onclick={createSchedule}
							disabled={creating}
							class="btn btn-primary"
						>
							{#if creating}생성 중...{:else}생성{/if}
						</button>
					</div>
				</div>
			{:else if selectedType === 'instagram_feed'}
						<p class="text-muted-foreground mb-4">수집할 Instagram 계정을 선택하세요</p>
						{#if serviceAccounts.length === 0}
							<p class="text-muted-foreground text-center py-4">등록된 계정이 없습니다</p>
						{:else}
							<div class="space-y-2 max-h-64 overflow-y-auto">
								{#each serviceAccounts as account}
									<button
										onclick={() => selectTarget({ id: account.id, name: account.profile_name ?? account.identifier ?? '' })}
										class="w-full flex items-center gap-3 p-3 border rounded-lg hover:border-blue-500 hover:bg-primary-light transition-colors text-left"
									>
										<div class="w-10 h-10 bg-pink-light rounded-full flex items-center justify-center text-pink">
											<Instagram size={20} />
										</div>
										<div>
											<div class="font-medium text-foreground">{account.profile_name || account.identifier}</div>
											<div class="text-sm text-muted-foreground">
												{account.is_logged_in ? '로그인됨' : '로그인 필요'}
											</div>
										</div>
									</button>
								{/each}
							</div>
						{/if}
					{:else if selectedType === 'google_search'}
						<!-- Google 검색: 새 검색어 입력 -->
						<p class="text-muted-foreground mb-4">검색 조건을 입력하세요</p>
						<div class="space-y-4">
								<div>
									<label for="new-query" class="block text-sm font-medium text-foreground mb-1">검색 키워드 *</label>
									<input
										id="new-query"
										type="text"
										bind:value={newSearchQuery}
										placeholder="검색할 키워드를 입력하세요"
										class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
									/>
								</div>

								<div>
									<label for="new-name" class="block text-sm font-medium text-foreground mb-1">저장 이름</label>
									<input
										id="new-name"
										type="text"
										bind:value={newSearchName}
										placeholder="자동 생성됨 (선택)"
										class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
									/>
								</div>

								<div class="grid grid-cols-2 gap-3">
									<div>
										<label for="new-datefilter" class="block text-sm font-medium text-foreground mb-1">기간 필터</label>
										<select
											id="new-datefilter"
											bind:value={newSearchDateFilter}
											class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
										>
											{#each dateFilterOptions as opt}
												<option value={opt.value}>{opt.label}</option>
											{/each}
										</select>
									</div>
									<div>
										<label for="new-maxpages" class="block text-sm font-medium text-foreground mb-1">수집 페이지</label>
										<input
											id="new-maxpages"
											type="number"
											min="1"
											max="10"
											bind:value={newSearchMaxPages}
											class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
										/>
									</div>
								</div>

								<!-- 고급 옵션 토글 -->
								<button
									onclick={() => (showAdvancedOptions = !showAdvancedOptions)}
									class="text-sm text-primary hover:text-primary-hover flex items-center gap-1"
								>
									{#if showAdvancedOptions}
										<ChevronDown size={14} />
									{:else}
										<ChevronRight size={14} />
									{/if} 고급 검색 옵션
								</button>

								{#if showAdvancedOptions}
									<div class="space-y-3 pl-3 border-l-2 border-border">
										<div>
											<label for="new-lr" class="block text-sm font-medium text-foreground mb-1">언어 제한</label>
											<select
												id="new-lr"
												bind:value={newSearchLr}
												class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
											>
												{#each languageOptions as opt}
													<option value={opt.value}>{opt.label}</option>
												{/each}
											</select>
										</div>
										<div>
											<label for="new-cr" class="block text-sm font-medium text-foreground mb-1">국가 제한</label>
											<select
												id="new-cr"
												bind:value={newSearchCr}
												class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
											>
												{#each countryOptions as opt}
													<option value={opt.value}>{opt.label}</option>
												{/each}
											</select>
										</div>
										<div>
											<label for="new-sitesearch" class="block text-sm font-medium text-foreground mb-1">사이트 제한</label>
											<input
												id="new-sitesearch"
												type="text"
												bind:value={newSearchSitesearch}
												placeholder="예: naver.com"
												class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
											/>
										</div>
									</div>
								{/if}

								<div class="flex justify-end">
									<button
										onclick={proceedWithNewSearch}
										class="btn btn-primary"
									>
										다음 →
									</button>
								</div>
						</div>
					{/if}

				{:else if addStep === 3}
					<!-- Step 3: 시간 설정 -->
					<div class="mb-4">
						<p class="text-muted-foreground mb-2">실행 시간을 설정하세요</p>
						{#if selectedType === 'google_search' && newSearchQuery}
							<p class="text-sm text-primary">
								검색어: {newSearchQuery}
								{#if newSearchDateFilter}
									| 기간: {dateFilterOptions.find(o => o.value === newSearchDateFilter)?.label}
								{/if}
							</p>
						{:else if selectedType === 'instagram_feed' && selectedTarget}
							<p class="text-sm text-primary">
								선택된 대상: {selectedTarget.name}
							</p>
						{/if}
					</div>

					<div class="space-y-3 mb-4">
						{#each scheduleTimes as time, i}
							<div class="flex items-center gap-2">
								<input
									type="time"
									bind:value={scheduleTimes[i]}
									class="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
								/>
								{#if scheduleTimes.length > 1}
									<button
										onclick={() => removeTime(i)}
										class="p-2 text-error hover:bg-error-light rounded-lg"
										title="삭제"
									>
										<X size={18} />
									</button>
								{/if}
							</div>
						{/each}
					</div>

					<button
						onclick={addTime}
						class="w-full py-2 border-2 border-dashed border-border rounded-lg text-muted-foreground hover:border-blue-500 hover:text-primary transition-colors flex items-center justify-center gap-1"
					>
						<Plus size={16} /> 시간 추가
					</button>

					<div class="mt-6 flex justify-end gap-2">
						<Button variant="secondary" onclick={closeAddModal}>
							취소
						</Button>
						<button
							onclick={createSchedule}
							disabled={creating}
							class="btn btn-primary"
						>
							{#if creating}
								생성 중...
							{:else}
								생성
							{/if}
						</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- 수정 모달 -->
{#if showEditModal && editSchedule}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-hidden">
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<h2 class="text-xl font-bold text-foreground">스케줄 수정</h2>
				<button
					onclick={closeEditModal}
					class="text-muted-foreground hover:text-muted-foreground text-2xl leading-none"
				>
					&times;
				</button>
			</div>

			<div class="p-6 overflow-y-auto max-h-[calc(90vh-80px)]">
				{#if editLoading}
					<div class="flex justify-center py-8">
						<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
					</div>
				{:else}
					<div class="space-y-5">
						<!-- 기본 정보 -->
						<div>
							<label for="edit-displayname" class="block text-sm font-medium text-foreground mb-1">표시 이름</label>
							<input
								id="edit-displayname"
								type="text"
								bind:value={editDisplayName}
								class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							/>
						</div>

						<!-- Google 검색 조건 (Google만) -->
						{#if editSchedule.target_type === 'google_search'}
							<div class="border-t border-border pt-4">
								<h3 class="font-medium text-foreground mb-3">검색 조건</h3>
								<div class="space-y-3">
									<div>
										<label for="edit-google-query" class="block text-sm font-medium text-foreground mb-1">검색 키워드 *</label>
										<input
											id="edit-google-query"
											type="text"
											bind:value={editGoogleQuery}
											class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
										/>
									</div>
									<div>
										<label for="edit-google-name" class="block text-sm font-medium text-foreground mb-1">저장 이름</label>
										<input
											id="edit-google-name"
											type="text"
											bind:value={editGoogleName}
											class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
										/>
									</div>
									<div class="grid grid-cols-2 gap-3">
										<div>
											<label for="edit-datefilter" class="block text-sm font-medium text-foreground mb-1">기간 필터</label>
											<select
												id="edit-datefilter"
												bind:value={editGoogleDateFilter}
												class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
											>
												{#each dateFilterOptions as opt}
													<option value={opt.value}>{opt.label}</option>
												{/each}
											</select>
										</div>
										<div>
											<label for="edit-maxpages" class="block text-sm font-medium text-foreground mb-1">수집 페이지</label>
											<input
												id="edit-maxpages"
												type="number"
												min="1"
												max="10"
												bind:value={editGoogleMaxPages}
												class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
											/>
										</div>
									</div>

									<!-- 고급 옵션 -->
									<button
										onclick={() => (editShowAdvanced = !editShowAdvanced)}
										class="text-sm text-primary hover:text-primary-hover flex items-center gap-1"
									>
										{#if editShowAdvanced}
											<ChevronDown size={14} />
										{:else}
											<ChevronRight size={14} />
										{/if} 고급 검색 옵션
									</button>

									{#if editShowAdvanced}
										<div class="space-y-3 pl-3 border-l-2 border-border">
											<div>
												<label for="edit-lr" class="block text-sm font-medium text-foreground mb-1">언어 제한</label>
												<select
													id="edit-lr"
													bind:value={editGoogleLr}
													class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
												>
													{#each languageOptions as opt}
														<option value={opt.value}>{opt.label}</option>
													{/each}
												</select>
											</div>
											<div>
												<label for="edit-cr" class="block text-sm font-medium text-foreground mb-1">국가 제한</label>
												<select
													id="edit-cr"
													bind:value={editGoogleCr}
													class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
												>
													{#each countryOptions as opt}
														<option value={opt.value}>{opt.label}</option>
													{/each}
												</select>
											</div>
											<div>
												<label for="edit-sitesearch" class="block text-sm font-medium text-foreground mb-1">사이트 제한</label>
												<input
													id="edit-sitesearch"
													type="text"
													bind:value={editGoogleSitesearch}
													placeholder="예: naver.com"
													class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
												/>
											</div>
										</div>
									{/if}
								</div>
							</div>
						{/if}

						<!-- LLM 설정 (instagram_feed, writing_task, topic_extract, pytest_run) -->
						{#if LLM_TARGET_TYPES.includes(editSchedule.target_type)}
							<div class="border-t border-border pt-4">
								<h3 class="font-medium text-foreground mb-3">LLM 설정</h3>
								<div class="space-y-3">
									<label class="flex items-center gap-3 text-sm text-foreground">
										<input
											type="checkbox"
											bind:checked={editLlmUseSystemDefaults}
											class="rounded border-border text-primary focus:ring-ring"
										/>
										<span>시스템 기본값 사용</span>
									</label>
									<div>
										<label for="edit-llm-provider" class="block text-sm font-medium text-foreground mb-1">LLM Provider</label>
										<select
											id="edit-llm-provider"
											bind:value={editLlmProvider}
											disabled={editLlmUseSystemDefaults}
											class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
										>
											{#if providers.length > 0}
												{#each providers as p}
													<option value={p.key}>{p.display_name}</option>
												{/each}
											{:else}
												<option value="claude">Claude</option>
												<option value="gemini">Gemini</option>
											{/if}
										</select>
									</div>
									<div>
										<label for="edit-llm-model" class="block text-sm font-medium text-foreground mb-1">모델명</label>
										<input
											id="edit-llm-model"
											type="text"
											bind:value={editLlmModel}
											disabled={editLlmUseSystemDefaults}
											placeholder="비워두면 기본 모델 사용"
											class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
										/>
									</div>
									{#if editLlmUseSystemDefaults}
										<p class="text-xs text-muted-foreground">
											저장 시 llm_provider / llm_model 키를 제거합니다.
										</p>
									{/if}
								</div>
							</div>
						{/if}

						<!-- 실행 시간 설정 -->
						<div class="border-t border-border pt-4">
							<h3 class="font-medium text-foreground mb-3">실행 시간</h3>
							{#if editSchedule && ['pytest_run', 'plan_archive_analyze', 'devguide_staleness', 'auto_dev_runner'].includes(editSchedule.target_type)}
								<div>
									<input
										type="time"
										bind:value={editCronTime}
										class="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
									/>
									<p class="text-xs text-muted-foreground mt-1">매일 1회 실행 (±5분 허용)</p>
								</div>
							{:else}
								<div class="space-y-3 mb-3">
									{#each editTimes as time, i}
										<div class="flex items-center gap-2">
											<input
												type="time"
												bind:value={editTimes[i]}
												class="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
											/>
											{#if editTimes.length > 1}
												<button
													onclick={() => editRemoveTime(i)}
													class="p-2 text-error hover:bg-error-light rounded-lg"
													title="삭제"
												>
													<X size={18} />
												</button>
											{/if}
										</div>
									{/each}
								</div>
								<button
									onclick={editAddTime}
									class="w-full py-2 border-2 border-dashed border-border rounded-lg text-muted-foreground hover:border-blue-500 hover:text-primary transition-colors text-sm flex items-center justify-center gap-1"
								>
									<Plus size={14} /> 시간 추가
								</button>
							{/if}
						</div>
						<!-- 저장 버튼 -->
						<div class="flex justify-end gap-2 pt-2">
							<Button variant="secondary" onclick={closeEditModal}>
								취소
							</Button>
							<button
								onclick={saveEdit}
								disabled={editSaving}
								class="btn btn-primary"
							>
								{#if editSaving}
									저장 중...
								{:else}
									저장
								{/if}
							</button>
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- 삭제 확인 모달 -->
{#if showDeleteModal && deleteTarget}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-md w-full">
			<div class="px-6 py-4 border-b border-border">
				<h2 class="text-xl font-bold text-foreground">스케줄 삭제</h2>
			</div>
			<div class="p-6">
				<p class="text-foreground mb-4">
					<strong>"{deleteTarget.display_name || deleteTarget.name}"</strong> 스케줄을 삭제하시겠습니까?
				</p>
				<p class="text-sm text-error bg-error-light p-3 rounded-lg">
					실행 이력도 함께 삭제됩니다. 이 작업은 되돌릴 수 없습니다.
				</p>
			</div>
			<div class="px-6 py-4 border-t border-border flex justify-end gap-2">
				<Button variant="secondary" onclick={closeDeleteModal} disabled={deleting}>
					취소
				</Button>
				<button
					onclick={confirmDelete}
					disabled={deleting}
					class="btn bg-error text-white hover:bg-error/90"
				>
					{#if deleting}
						삭제 중...
					{:else}
						삭제
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
