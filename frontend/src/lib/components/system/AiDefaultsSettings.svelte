<script lang="ts">
	import { onMount } from 'svelte';
	import { collectApi } from '$lib/api';
	import { llmApi, type LLMDefaultsResponse } from '$lib/api/system';
	import {
		devRunnerSettingsApi,
		devRunnerEngineApi,
		type DevRunnerSettings,
		type AllEnginesConfig
	} from '$lib/api/dev-runner';
	import { confirm } from '$lib/stores/confirm';
	import type { CrawlSchedule } from '$lib/types';

	type CallerDraft = { provider: string; model: string };

	const ENGINE_OPTIONS = ['claude', 'gemini', 'codex', 'cc-codex'];

	let loading = true;
	let savingLlm = false;
	let savingEngines = false;
	let savingModels = false;
	let errorMessage = '';
	let successMessage = '';

	let llmDefaults: LLMDefaultsResponse | null = null;
	let devRunnerSettings: DevRunnerSettings | null = null;
	let engineConfigs: AllEnginesConfig = {};
	let schedulerSchedules: CrawlSchedule[] = [];
	let schedulerRuntimeSummary: Awaited<ReturnType<typeof llmApi.getSchedulerRuntimeSummary>> | null = null;

	let globalProvider = 'claude';
	let globalModel = '';
	let callerDrafts: Record<string, CallerDraft> = {};

	let defaultEngine = 'claude';
	let defaultFixEngine = 'claude';

	let bulkEngine = '';
	let bulkModel = '';

	function setLlmDrafts(data: LLMDefaultsResponse) {
		llmDefaults = data;
		globalProvider = data.global_default?.provider ?? 'claude';
		globalModel = data.global_default?.model ?? '';

		const nextDrafts: Record<string, CallerDraft> = {};
		for (const callerType of data.known_caller_types ?? []) {
			const current = data.caller_defaults?.[callerType];
			nextDrafts[callerType] = {
				provider: current?.provider ?? '',
				model: current?.model ?? ''
			};
		}
		callerDrafts = nextDrafts;
	}

	function setDevRunnerDrafts(data: DevRunnerSettings) {
		devRunnerSettings = data;
		defaultEngine = data.default_engine || 'claude';
		defaultFixEngine = data.default_fix_engine || 'claude';
	}

	function getModelOptions(engine: string): string[] {
		const config = engineConfigs?.[engine];
		if (!config) return [];
		const models = [config.default_model, ...Object.values(config.models ?? {})]
			.filter((value): value is string => Boolean(value && value.trim()));
		return Array.from(new Set(models));
	}

	function resetBulkModel(engine: string) {
		const config = engineConfigs?.[engine];
		bulkModel = config?.default_model ?? '';
	}

	async function loadData() {
		loading = true;
		errorMessage = '';
		try {
			const [llm, devRunner, engines, schedules, runtime] = await Promise.all([
				llmApi.getDefaults(),
				devRunnerSettingsApi.get(),
				devRunnerEngineApi.list(),
				collectApi.getSchedules(),
				llmApi.getSchedulerRuntimeSummary()
			]);
			setLlmDrafts(llm);
			setDevRunnerDrafts(devRunner);
			engineConfigs = engines;
			schedulerSchedules = schedules;
			schedulerRuntimeSummary = runtime;
			bulkEngine = Object.keys(engines)[0] ?? 'claude';
			resetBulkModel(bulkEngine);
		} catch (e) {
			errorMessage = e instanceof Error ? e.message : 'AI 기본값 로드 실패';
		} finally {
			loading = false;
		}
	}

	function showSuccess(message: string) {
		successMessage = message;
		setTimeout(() => {
			successMessage = '';
		}, 2500);
	}

	async function saveLlmDefaults() {
		if (!llmDefaults) return;
		savingLlm = true;
		errorMessage = '';
		try {
			const callerDefaults: Record<string, { provider?: string | null; model?: string | null }> = {};
			for (const callerType of llmDefaults.known_caller_types) {
				const draft = callerDrafts[callerType] ?? { provider: '', model: '' };
				callerDefaults[callerType] = {
					provider: draft.provider || null,
					model: draft.model ?? ''
				};
			}

			const updated = await llmApi.updateDefaults({
				global_default: {
					provider: globalProvider,
					model: globalModel
				},
				caller_defaults: callerDefaults
			});
			setLlmDrafts(updated);
			showSuccess('LLM 기본값 저장 완료');
		} catch (e) {
			errorMessage = e instanceof Error ? e.message : 'LLM 기본값 저장 실패';
		} finally {
			savingLlm = false;
		}
	}

	async function saveDevRunnerDefaults() {
		savingEngines = true;
		errorMessage = '';
		try {
			const updated = await devRunnerSettingsApi.update({
				default_engine: defaultEngine,
				default_fix_engine: defaultFixEngine
			});
			setDevRunnerDrafts(updated);
			showSuccess('dev-runner 기본 엔진 저장 완료');
		} catch (e) {
			errorMessage = e instanceof Error ? e.message : 'dev-runner 기본 엔진 저장 실패';
		} finally {
			savingEngines = false;
		}
	}

	async function overwriteAllPhaseModels() {
		if (!bulkEngine) {
			errorMessage = '엔진을 선택하세요.';
			return;
		}
		const nextModel = bulkModel.trim();
		if (!nextModel) {
			errorMessage = '모델명을 입력하세요.';
			return;
		}
		if (
			!(await confirm({
				title: 'Phase 모델 덮어쓰기',
				message: `${bulkEngine} 엔진의 모든 phase 모델을 "${nextModel}"으로 덮어쓸까요?`,
				confirmText: '덮어쓰기',
				variant: 'warning'
			}))
		) {
			return;
		}

		savingModels = true;
		errorMessage = '';
		try {
			await devRunnerEngineApi.update(bulkEngine, {
				default_model: nextModel,
				overwrite_all_phases: true
			});
			engineConfigs = await devRunnerEngineApi.list();
			resetBulkModel(bulkEngine);
			showSuccess('phase 모델 일괄 덮어쓰기 완료');
		} catch (e) {
			errorMessage = e instanceof Error ? e.message : 'phase 모델 일괄 덮어쓰기 실패';
		} finally {
			savingModels = false;
		}
	}

	function getActiveSchedulePinCount() {
		return schedulerSchedules.filter((schedule) => schedule.enabled && schedule.resolution_source === 'schedule_pin').length;
	}

	function getLegacyCandidateCount() {
		return schedulerSchedules.filter((schedule) => schedule.enabled && schedule.legacy_placeholder_candidate).length;
	}

	function getRecentProviderSummary() {
		const top = schedulerRuntimeSummary?.provider_summary?.[0];
		if (!top) return '최근 scheduler 실행 없음';
		const model = top.model ? ` / ${top.model}` : '';
		return `${top.provider}${model} (${top.count}건)`;
	}

	onMount(loadData);
</script>

<div class="space-y-6">
	{#if loading}
		<p class="text-sm text-muted-foreground">AI 기본값을 불러오는 중...</p>
	{:else}
		{#if errorMessage}
			<div class="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{errorMessage}</div>
		{/if}
		{#if successMessage}
			<div class="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">{successMessage}</div>
		{/if}

		<section class="rounded-lg border border-border p-4 space-y-4">
			<div class="grid gap-3 sm:grid-cols-3">
				<div class="rounded border border-border bg-muted/30 p-3">
					<div class="text-xs text-muted-foreground">활성 schedule pin</div>
					<div class="mt-1 text-lg font-semibold">{getActiveSchedulePinCount()}건</div>
				</div>
				<div class="rounded border border-border bg-muted/30 p-3">
					<div class="text-xs text-muted-foreground">legacy 후보</div>
					<div class="mt-1 text-lg font-semibold">{getLegacyCandidateCount()}건</div>
				</div>
				<div class="rounded border border-border bg-muted/30 p-3">
					<div class="text-xs text-muted-foreground">최근 scheduler provider</div>
					<div class="mt-1 text-sm font-semibold">{getRecentProviderSummary()}</div>
				</div>
			</div>

			<div class="flex items-center justify-between gap-3">
				<div>
					<h3 class="text-sm font-semibold">LLMWorker 기본값</h3>
					<p class="text-xs text-muted-foreground">요청값 미지정 시 caller별 기본 provider/model을 적용합니다.</p>
				</div>
				<button class="save-btn" onclick={saveLlmDefaults} disabled={savingLlm}>
					{savingLlm ? '저장 중...' : '저장'}
				</button>
			</div>

			<div class="grid gap-3 sm:grid-cols-2">
				<label class="field">
					<span>Global Provider</span>
					<select bind:value={globalProvider}>
						{#each llmDefaults?.supported_providers ?? [] as provider}
							<option value={provider}>{provider}</option>
						{/each}
					</select>
				</label>
				<label class="field">
					<span>Global Model</span>
					<input type="text" bind:value={globalModel} placeholder="비우면 provider 기본 모델" />
				</label>
			</div>

			<div class="overflow-auto rounded border border-border">
				<table class="w-full text-xs">
					<thead class="bg-muted/50 text-muted-foreground">
						<tr>
							<th class="th">caller_type</th>
							<th class="th">provider</th>
							<th class="th">model</th>
						</tr>
					</thead>
					<tbody>
						{#each llmDefaults?.known_caller_types ?? [] as callerType}
							<tr class="border-t border-border">
								<td class="td font-mono">{callerType}</td>
								<td class="td">
									<select bind:value={callerDrafts[callerType].provider}>
										<option value="">global fallback</option>
										{#each llmDefaults?.supported_providers ?? [] as provider}
											<option value={provider}>{provider}</option>
										{/each}
									</select>
								</td>
								<td class="td">
									<input type="text" bind:value={callerDrafts[callerType].model} placeholder="비우면 global model" />
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>

		<section class="rounded-lg border border-border p-4 space-y-4">
			<div class="flex items-center justify-between gap-3">
				<div>
					<h3 class="text-sm font-semibold">dev-runner 기본 엔진</h3>
					<p class="text-xs text-muted-foreground">Run 요청에서 engine/fix_engine 미지정 시 적용됩니다.</p>
				</div>
				<button class="save-btn" onclick={saveDevRunnerDefaults} disabled={savingEngines}>
					{savingEngines ? '저장 중...' : '저장'}
				</button>
			</div>

			<div class="grid gap-3 sm:grid-cols-2">
				<label class="field">
					<span>Default Engine</span>
					<select bind:value={defaultEngine}>
						{#each ENGINE_OPTIONS as engine}
							<option value={engine}>{engine}</option>
						{/each}
					</select>
				</label>
				<label class="field">
					<span>Default Fix Engine</span>
					<select bind:value={defaultFixEngine}>
						{#each ENGINE_OPTIONS as engine}
							<option value={engine}>{engine}</option>
						{/each}
					</select>
				</label>
			</div>

			{#if devRunnerSettings?.updated_at}
				<p class="text-xs text-muted-foreground">최종 변경: {new Date(devRunnerSettings.updated_at).toLocaleString()}</p>
			{/if}
		</section>

		<section class="rounded-lg border border-border p-4 space-y-4">
			<div class="flex items-center justify-between gap-3">
				<div>
					<h3 class="text-sm font-semibold">dev-runner 모델 일괄 설정</h3>
					<p class="text-xs text-muted-foreground">선택한 엔진의 `default_model`과 모든 phase `models[*]`를 동시에 덮어씁니다.</p>
				</div>
				<button class="save-btn" onclick={overwriteAllPhaseModels} disabled={savingModels}>
					{savingModels ? '적용 중...' : '전체 phase 덮어쓰기'}
				</button>
			</div>

			<div class="grid gap-3 sm:grid-cols-2">
				<label class="field">
					<span>대상 엔진</span>
					<select
						bind:value={bulkEngine}
						onchange={(event) => {
							bulkEngine = event.currentTarget.value;
							resetBulkModel(bulkEngine);
						}}
					>
						{#each Object.keys(engineConfigs) as engine}
							<option value={engine}>{engine}</option>
						{/each}
					</select>
				</label>
				<label class="field">
					<span>일괄 모델</span>
					<input list="bulk-models" type="text" bind:value={bulkModel} placeholder="모델명 입력" />
					<datalist id="bulk-models">
						{#each getModelOptions(bulkEngine) as model}
							<option value={model}></option>
						{/each}
					</datalist>
				</label>
			</div>
		</section>
	{/if}
</div>

<style>
	.save-btn {
		border: 1px solid #2563eb;
		background: #2563eb;
		color: white;
		padding: 0.35rem 0.75rem;
		font-size: 0.75rem;
		font-weight: 600;
		border-radius: 0.375rem;
	}

	.save-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		font-size: 0.75rem;
		color: #6b7280;
	}

	.field input,
	.field select {
		border: 1px solid #d1d5db;
		border-radius: 0.375rem;
		padding: 0.45rem 0.55rem;
		font-size: 0.8rem;
		background: white;
		color: #111827;
	}

	.th {
		padding: 0.5rem 0.55rem;
		text-align: left;
		font-weight: 600;
	}

	.td {
		padding: 0.45rem 0.55rem;
		vertical-align: middle;
	}

	.td input,
	.td select {
		width: 100%;
		border: 1px solid #d1d5db;
		border-radius: 0.35rem;
		padding: 0.35rem 0.45rem;
		font-size: 0.75rem;
	}
</style>
