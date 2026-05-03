<script lang="ts">
import { X } from 'lucide-svelte';
import { devRunnerRunnerApi, devRunnerPlanApi, devRunnerEngineApi, devRunnerSettingsApi } from '$lib/api';
import type {
	DevRunnerRunStatusResponse,
	DevRunnerPlanFileResponse,
	AllEnginesConfig,
	EngineConfig
} from '$lib/api';
import { llmApi } from '$lib/api/system';
import type { LLMProfilesResponse } from '$lib/api/system';
import { onMount, onDestroy } from 'svelte';
import ExecuteModalShell from '$lib/components/dev-runner/execute-modal/ExecuteModalShell.svelte';
import PlanIdentityHeader from '$lib/components/dev-runner/execute-modal/PlanIdentityHeader.svelte';
import ActionBar from '$lib/components/dev-runner/execute-modal/ActionBar.svelte';
import ExecutionSettingsForm from '$lib/components/dev-runner/execute-modal/ExecutionSettingsForm.svelte';
import SummaryProgress from '$lib/components/dev-runner/execute-modal/SummaryProgress.svelte';
import { confirm } from '$lib/stores/confirm';

	interface Props {
		open?: boolean;
		onClose?: () => void;
		plan?: DevRunnerPlanFileResponse | null;
		summaryGenerating?: boolean;
		summaryGenerated?: boolean;
		onGenerateSummary?: () => void | Promise<void>;
		status: DevRunnerRunStatusResponse | null;
		plans: DevRunnerPlanFileResponse[];
		onStatusChange: () => void;
		onStart?: (response: DevRunnerRunStatusResponse) => void;
		selectedPlan?: string;
		mode?: 'single' | 'all';
		runnerTabs?: { id: string; running: boolean }[];
		hidePlanSelector?: boolean;
	}

	let {
		open = true,
		onClose = () => {},
		plan = null,
		summaryGenerating = false,
		summaryGenerated = false,
		onGenerateSummary,
		status,
		plans,
		onStatusChange,
		onStart,
		selectedPlan = $bindable(''),
		mode = $bindable('single'),
		runnerTabs = [],
		hidePlanSelector = false
	}: Props = $props();
	let selectedEngine = $state('claude');
	let selectedFixEngine = $state('claude');
	let profilesData = $state<LLMProfilesResponse | null>(null);
	let selectedProfile = $state<string | null>(null);
	let profilesForEngine = $derived(profilesData?.profiles.filter(p => p.engine === selectedEngine) ?? []);
	let showProfileSelect = $derived(profilesForEngine.length > 1);
	let engineConfigs = $state<AllEnginesConfig | null>(null);
	let selectedEngineConfig = $derived(engineConfigs?.[selectedEngine] ?? null);
	let selectedEngineModelOptions = $derived(getModelOptions(selectedEngine));
	let selectedEnginePhases = $derived(getPhaseKeys(selectedEngineConfig));
	let maxCycles = $state(0);

	let runningEngine = $derived(status?.engine ?? 'claude');
	let until = $state('');
	let dryRun = $state(false);
	let worktree = $state(true);
	let parallel = $state(false);
	let projects = $state('');
	let planSummary = $derived(plans.find(p => p.path === selectedPlan)?.summary ?? '');
	let selectedPlanArchived = $derived(mode === 'single' && selectedPlan ? isArchivedPlanPath(selectedPlan) : false);
	let anyRunning = $derived(runnerTabs.some(t => t.running));
	let actionLoading = $state(false);
	let actionError = $state<string | null>(null);
	let syncMessage = $state<string | null>(null);
	let forceStopNeeded = $state(false);
	let syncMessageTimer: ReturnType<typeof setTimeout> | null = null;

	// 엔진별 fallback 모델 리스트 (engines API 실패/누락 시에만 사용)
	const PREDEFINED_MODELS: Record<string, string[]> = {
		claude: [
			'opus',
			'sonnet',
			'haiku'
		],
		gemini: [
			'gemini-3.1-pro-preview',
			'gemini-3.1-pro',
			'gemini-3-flash-preview',
			'gemini-3-pro-preview',
			'gemini-2.5-pro-preview-05-06',
			'gemini-2.0-flash-thinking-exp',
			'gemini-2.0-flash'
		],
		codex: [
			'gpt-5.4',
			'gpt-5.3-codex',
			'o3'
		],
		'cc-codex': [
			'opus',
			'sonnet',
			'haiku'
		]
	};
	const DEFAULT_ENGINE_OPTIONS = ['claude', 'gemini', 'codex', 'cc-codex'];

	const ENGINE_LABELS: Record<string, string> = {
		claude: 'Claude',
		gemini: 'Gemini',
		codex: 'Codex',
		'cc-codex': 'CC-Codex'
	};

	const ENGINE_THEME_CLASSES: Record<string, string> = {
		claude: 'text-sky-700 bg-sky-50 border-sky-200',
		gemini: 'text-orange-700 bg-orange-50 border-orange-200',
		codex: 'text-slate-700 bg-slate-50 border-slate-300',
		'cc-codex': 'text-emerald-700 bg-emerald-50 border-emerald-200'
	};
const PHASE_PRIORITY = ['plan', 'impl', 'done', 'auto-conflict-resolver', 'auto-verify'];

	function isArchivedPlanPath(path: string): boolean {
		return path.includes('/archive/') || path.includes('\\archive\\');
	}

	function resetTransientActionState() {
		actionError = null;
		syncMessage = null;
		forceStopNeeded = false;
		if (syncMessageTimer) {
			clearTimeout(syncMessageTimer);
			syncMessageTimer = null;
		}
	}

	function getConfiguredEngines(): string[] {
		if (!engineConfigs) return [];
		return Object.entries(engineConfigs)
			.filter(([, config]) => Boolean(config?.default_model))
			.map(([engine]) => engine);
	}

	function getEngineOptions(): string[] {
		const configured = getConfiguredEngines();
		if (configured.length > 0) return configured;
		return DEFAULT_ENGINE_OPTIONS;
	}

	function normalizeSelectedEngines() {
		const configured = getConfiguredEngines();
		const options = configured.length > 0 ? configured : getEngineOptions();
		if (options.length === 0) return;
		if (!options.includes(selectedEngine)) {
			selectedEngine = options[0];
		}
		if (!options.includes(selectedFixEngine)) {
			selectedFixEngine = options[0];
		}
	}

	function getModelOptions(engine: string): string[] {
		const predefined = PREDEFINED_MODELS[engine] ?? [];
		const config = engineConfigs?.[engine];
		if (config) {
			const fromConfig = [config.default_model, ...Object.values(config.models ?? {})]
				.filter((model): model is string => Boolean(model && model.trim()));
			const merged = [...fromConfig, ...predefined];
			return Array.from(new Set(merged));
		}

		return predefined;
	}

	function sortPhaseKeys(keys: string[]): string[] {
		const unique = Array.from(new Set(keys.filter((key) => Boolean(key && key.trim()))));
		return unique.sort((a, b) => {
			const aPriority = PHASE_PRIORITY.indexOf(a);
			const bPriority = PHASE_PRIORITY.indexOf(b);
			const aInPriority = aPriority !== -1;
			const bInPriority = bPriority !== -1;
			if (aInPriority || bInPriority) {
				if (!aInPriority) return 1;
				if (!bInPriority) return -1;
				if (aPriority !== bPriority) return aPriority - bPriority;
			}
			return a.localeCompare(b);
		});
	}

	function getPhaseKeys(config: EngineConfig | null): string[] {
		if (!config?.models) return ['plan', 'impl', 'done'];
		const modelKeys = Object.keys(config.models);
		if (modelKeys.length === 0) return ['plan', 'impl', 'done'];
		return sortPhaseKeys(modelKeys);
	}

	function getPhaseModel(phase: string): string {
		if (selectedEngineConfig) {
			return selectedEngineConfig.models?.[phase] ?? selectedEngineConfig.default_model;
		}
		return selectedEngineModelOptions[0] ?? '';
	}

	function getPhaseSelectId(phase: string, index: number): string {
		const normalized = phase
			.toLowerCase()
			.replace(/[^a-z0-9_-]+/g, '-')
			.replace(/^-+|-+$/g, '');
		return `phase-model-${normalized || 'default'}-${index}`;
	}

	function formatEngineLabel(engine: string): string {
		return ENGINE_LABELS[engine] ?? engine;
	}

	function getEngineThemeClasses(engine: string): string {
		return ENGINE_THEME_CLASSES[engine] ?? 'text-muted-foreground bg-muted border-border';
	}

	async function fetchEngineConfigs() {
		try {
			engineConfigs = await devRunnerEngineApi.list();
			normalizeSelectedEngines();
		} catch (e) {
			console.warn('Failed to fetch engine configs', e);
			normalizeSelectedEngines();
		}
	}

	async function fetchDefaultEngines() {
		try {
			const settings = await devRunnerSettingsApi.get();
			if (settings.default_engine) {
				selectedEngine = settings.default_engine;
			}
			if (settings.default_fix_engine) {
				selectedFixEngine = settings.default_fix_engine;
			}
			normalizeSelectedEngines();
		} catch (e) {
			console.warn('Failed to fetch dev-runner defaults', e);
		}
	}

	onMount(() => {
		fetchEngineConfigs();
		fetchDefaultEngines();
		llmApi.listProfiles().then(d => {
			profilesData = d;
			// 현재 선택된 엔진의 선택 프로필로 초기화
			selectedProfile = d.selected[selectedEngine] ?? null;
		}).catch(() => {});
	});

	$effect(() => {
		if (!engineConfigs) return;
		normalizeSelectedEngines();
	});

	// 엔진 변경 시 프로필 자동 갱신
	$effect(() => {
		if (!profilesData) return;
		selectedProfile = profilesData.selected[selectedEngine] ?? null;
	});

	async function updateModel(phase: string, model: string) {
		if (!selectedEngineConfig || !selectedEngine) return;
		try {
			const overwriteAll = await confirm({
				title: 'Phase 모델 덮어쓰기',
				message: `"${selectedEngine}" 엔진의 모든 phase 모델을 "${model}"로 덮어쓸까요?\n취소하면 현재 phase만 변경됩니다.`,
				confirmText: '전체 덮어쓰기'
			});
			if (overwriteAll) {
				await devRunnerEngineApi.update(selectedEngine, {
					default_model: model,
					overwrite_all_phases: true
				});
				await fetchEngineConfigs();
				return;
			}

			const nextModels: Record<string, string> = { ...selectedEngineConfig.models, [phase]: model };
			await devRunnerEngineApi.update(selectedEngine, { models: nextModels });
			engineConfigs = {
				...(engineConfigs ?? {}),
				[selectedEngine]: {
					...selectedEngineConfig,
					models: nextModels,
				}
			};
		} catch (e) {
			actionError = '모델 변경 실패';
		}
	}

	async function handleStart() {
		if (mode === 'single' && !selectedPlan) {
			actionError = 'Plan 파일을 선택하세요';
			return;
		}
		if (mode === 'single' && selectedPlan) {
			const selected = plans.find(p => p.path === selectedPlan);
			if ((selected?.path != null && isArchivedPlanPath(selected.path)) || isArchivedPlanPath(selectedPlan)) {
				actionError = '아카이브된 Plan은 실행할 수 없습니다.';
				return;
			}
		}
		actionLoading = true;
		actionError = null;
		forceStopNeeded = false;
		try {
			const response = await devRunnerRunnerApi.start({
				plan_file: mode === 'single' ? selectedPlan : null,
				engine: selectedEngine,
				fix_engine: selectedFixEngine,
				profile: selectedProfile,
				max_cycles: maxCycles || 0,
				until: until || null,
				dry_run: dryRun,
				parallel: mode === 'all' ? true : parallel,
				projects: projects || null,
				worktree,
				trigger: mode === 'all' ? 'user:all' : 'user',
			});
			onStatusChange();
			onStart?.(response);
		} catch (e) {
			const msg = e instanceof Error ? e.message : '시작 실패';
			if (msg.includes('Already running')) {
				// 실제 실행 중 → 상태 즉시 새로고침 (중지 버튼이 자동으로 표시됨)
				onStatusChange();
				actionError = msg;
				forceStopNeeded = true;
			} else if (msg.includes('archived plan') || msg.includes('archive')) {
				actionError = '이 Plan은 아카이브되어 실행할 수 없습니다. Plans 탭에서 아카이브 목록을 확인하세요.';
			} else if (msg.includes('Redis') || msg.includes('listener') || msg.includes('503') || msg.includes('504')) {
				actionError = `${msg} — Redis와 dev-runner listener가 실행 중인지 확인하세요.`;
			} else {
				actionError = msg;
			}
		} finally {
			actionLoading = false;
		}
	}

	async function handleForceStop() {
		actionLoading = true;
		actionError = null;
		forceStopNeeded = false;
		try {
			await devRunnerRunnerApi.resetState(false);
			onStatusChange();
		} catch (e) {
			actionError = e instanceof Error ? e.message : '강제 중지 실패';
		} finally {
			actionLoading = false;
		}
	}

	async function handleStop() {
		if (!await confirm({ title: '실행 중지', message: '실행을 중지하시겠습니까?', confirmText: '중지' })) return;
		actionLoading = true;
		actionError = null;
		try {
			await devRunnerRunnerApi.stopAll();
			onStatusChange();
		} catch (e) {
			actionError = e instanceof Error ? e.message : '중지 실패';
		} finally {
			actionLoading = false;
		}
	}

	async function handleSync() {
		actionLoading = true;
		actionError = null;
		syncMessage = null;
		if (syncMessageTimer) {
			clearTimeout(syncMessageTimer);
			syncMessageTimer = null;
		}
		try {
			const result = await devRunnerPlanApi.sync();
			onStatusChange();
			const parts: string[] = [];
			if (result.added > 0) parts.push(`${result.added}개 추가`);
			if (result.removed > 0) parts.push(`${result.removed}개 제거`);
			if (result.updated > 0) parts.push(`${result.updated}개 변경`);
			syncMessage = parts.length > 0
				? `동기화 완료: ${parts.join(', ')} (총 ${result.synced}개)`
				: `동기화 완료: 변경 없음 (총 ${result.synced}개)`;
			syncMessageTimer = setTimeout(() => {
				syncMessage = null;
				syncMessageTimer = null;
			}, 5000);
		} catch (e) {
			actionError = e instanceof Error ? e.message : '동기화 실패';
		} finally {
			actionLoading = false;
		}
	}

	async function handleResetState(fullReset: boolean = false) {
		const msg = fullReset
			? '전체 리셋: 모든 작업 기록을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.'
			: 'RUNNING 상태를 초기화하시겠습니까?\n미완료 작업이 PENDING으로 복구됩니다.';
		if (!await confirm({
			title: fullReset ? '전체 리셋' : 'RUNNING 상태 초기화',
			message: msg,
			confirmText: fullReset ? '전체 리셋' : '초기화',
			variant: fullReset ? 'danger' : 'default'
		})) return;
		actionLoading = true;
		actionError = null;
		try {
			const result = await devRunnerRunnerApi.resetState(fullReset);
			console.log(`${result.reset_count}개 작업 ${fullReset ? '삭제' : '초기화'}됨`);
			onStatusChange();
		} catch (e) {
			actionError = e instanceof Error ? e.message : '초기화 실패';
		} finally {
			actionLoading = false;
		}
	}

	onDestroy(() => {
		if (syncMessageTimer) {
			clearTimeout(syncMessageTimer);
			syncMessageTimer = null;
		}
	});

	$effect(() => {
		if (!open) {
			resetTransientActionState();
		}
	});
</script>

	{#if open}
		<ExecuteModalShell open={open} onClose={onClose} titleId={plan ? 'plan-modal-title' : 'execute-modal-title'}>
			{#snippet header()}
				{#if plan}
					<PlanIdentityHeader
						filename={plan.filename}
						status={plan.status}
						runningEngine={status?.running ? status.engine ?? null : null}
						titleId="plan-modal-title"
						onClose={onClose}
					/>
				{:else}
					<div class="flex items-center justify-between border-b border-border px-5 py-3.5 shrink-0">
						<h2 id="execute-modal-title" class="font-mono text-sm font-medium text-foreground">실행 설정</h2>
						<button
							type="button"
							onclick={onClose}
							class="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
							aria-label="닫기"
						>
							<X class="h-3.5 w-3.5" />
						</button>
					</div>
				{/if}
			{/snippet}

			{#snippet banner()}
				{#if actionError}
					<div class="flex items-center justify-between gap-2 bg-destructive px-5 py-2 text-xs text-destructive-foreground">
						<span>{actionError}</span>
						{#if forceStopNeeded}
							<button
								type="button"
								class="shrink-0 rounded-md border border-destructive-foreground/40 px-2 py-0.5 text-[10px] font-medium transition-colors hover:bg-destructive-foreground/10 disabled:opacity-50"
								onclick={handleForceStop}
								disabled={actionLoading}
							>
								강제 중지
							</button>
						{/if}
					</div>
				{/if}

				{#if syncMessage}
					<div class="bg-success-light px-5 py-2 text-xs text-success">{syncMessage}</div>
				{/if}

				{#if plan && mode !== 'all'}
					<SummaryProgress
						summaryKey={plan.path}
						summary={plan.summary ?? null}
						summaryGenerating={summaryGenerating}
						summaryGenerated={summaryGenerated}
						progress={plan.progress ?? null}
						worktreeBranch={plan.branch ?? null}
						worktreePath={plan.worktree_path ?? null}
						worktreeOwner={plan.worktree_owner ?? null}
						redisRunning={status?.redis_connected ?? false}
						listenerRunning={status?.listener_alive ?? false}
						onRegenerate={onGenerateSummary ?? (() => {})}
					/>
				{/if}
			{/snippet}

			<div class="min-h-full p-5">
				<ExecutionSettingsForm
					plans={plans}
					bind:selectedPlan={selectedPlan}
					bind:mode={mode}
					bind:selectedEngine={selectedEngine}
					bind:selectedFixEngine={selectedFixEngine}
					bind:selectedProfile={selectedProfile}
					bind:maxCycles={maxCycles}
					bind:until={until}
					bind:dryRun={dryRun}
					bind:worktree={worktree}
					bind:parallel={parallel}
					bind:projects={projects}
					selectedEngineConfig={selectedEngineConfig}
					selectedEnginePhases={selectedEnginePhases}
					selectedEngineModelOptions={selectedEngineModelOptions}
					profilesForEngine={profilesForEngine}
					showProfileSelect={showProfileSelect}
					hidePlanSelector={hidePlanSelector}
					selectedPlanArchived={selectedPlanArchived}
					planSummary={planSummary}
					runningEngine={status?.running ? runningEngine : null}
					getEngineOptions={getEngineOptions}
					getEngineThemeClasses={getEngineThemeClasses}
					formatEngineLabel={formatEngineLabel}
					getPhaseSelectId={getPhaseSelectId}
					getPhaseModel={getPhaseModel}
					onUpdateModel={updateModel}
				/>
			</div>

			{#snippet actions()}
				<ActionBar
					status={status}
					anyRunning={anyRunning}
					actionLoading={actionLoading}
					mode={mode}
					selectedPlan={selectedPlan}
					selectedPlanArchived={selectedPlanArchived}
					onStop={handleStop}
					onSync={handleSync}
					onReset={() => handleResetState(false)}
					onFullReset={() => handleResetState(true)}
					onStart={handleStart}
				/>
			{/snippet}
		</ExecuteModalShell>
	{/if}
