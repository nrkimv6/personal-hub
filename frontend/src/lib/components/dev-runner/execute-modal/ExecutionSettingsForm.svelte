<script lang="ts">
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { EngineConfig, DevRunnerPlanFileResponse } from '$lib/api';

	interface ProfileItem {
		name: string;
	}

	interface Props {
		plans: DevRunnerPlanFileResponse[];
		selectedPlan: string;
		mode: 'single' | 'all';
		selectedEngine: string;
		selectedFixEngine: string;
		selectedProfile: string | null;
		maxCycles: number;
		until: string;
		dryRun: boolean;
		worktree: boolean;
		parallel: boolean;
		projects: string;
		selectedEngineConfig: EngineConfig | null;
		selectedEnginePhases: string[];
		selectedEngineModelOptions: string[];
		profilesForEngine: ProfileItem[];
		showProfileSelect: boolean;
		hidePlanSelector: boolean;
		selectedPlanArchived: boolean;
		planSummary: string;
		runningEngine: string | null;
		getEngineOptions: () => string[];
		getEngineThemeClasses: (engine: string) => string;
		formatEngineLabel: (engine: string) => string;
		getPhaseSelectId: (phase: string, index: number) => string;
		getPhaseModel: (phase: string) => string;
		onUpdateModel: (phase: string, model: string) => void;
	}

	let {
		plans,
		selectedPlan = $bindable(''),
		mode = $bindable('single'),
		selectedEngine = $bindable('claude'),
		selectedFixEngine = $bindable('claude'),
		selectedProfile = $bindable(null),
		maxCycles = $bindable(0),
		until = $bindable(''),
		dryRun = $bindable(false),
		worktree = $bindable(true),
		parallel = $bindable(false),
		projects = $bindable(''),
		selectedEngineConfig,
		selectedEnginePhases,
		selectedEngineModelOptions,
		profilesForEngine,
		showProfileSelect,
		hidePlanSelector,
		selectedPlanArchived,
		planSummary,
		runningEngine,
		getEngineOptions,
		getEngineThemeClasses,
		formatEngineLabel,
		getPhaseSelectId,
		getPhaseModel,
		onUpdateModel
	}: Props = $props();

	let advancedOpen = $state(false);

	function isArchivedPlanPath(path: string): boolean {
		return path.includes('/archive/') || path.includes('\\archive\\');
	}
</script>

<div class="px-5 py-4 space-y-4">
	<div class="grid grid-cols-2 gap-x-4 gap-y-3">
		{#if !hidePlanSelector}
			<div class="col-span-2">
				{#if mode === 'single'}
					<div class="flex flex-col gap-0.5">
						<div class="flex items-center gap-2 min-w-0">
							<label for="plan-select" class="text-xs text-muted-foreground shrink-0">Plan</label>
							<select
								id="plan-select"
								class="h-8 w-[200px] rounded-md border border-border bg-card px-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary"
								bind:value={selectedPlan}
							>
								<option value="">Plan 선택...</option>
								{#each plans.filter((p) => !isArchivedPlanPath(p.path)) as plan}
									<option value={plan.path}>{plan.filename}{plan.progress != null ? ` (${plan.progress.percent}%)` : ''}</option>
								{/each}
							</select>
						</div>
						{#if planSummary}
							<p class="text-[10px] font-mono leading-relaxed text-muted-foreground line-clamp-2">{planSummary}</p>
						{/if}
					</div>
				{:else}
					<span class="text-xs text-muted-foreground">모든 미완료 Plan 자동 실행</span>
				{/if}
			</div>
		{:else}
			<div class="col-span-2 flex items-center gap-2 text-xs text-muted-foreground">
				<span>실행 대상:</span>
				<span class="min-w-0 flex-1 truncate font-mono text-foreground">{selectedPlan || '선택 없음'}</span>
			</div>
		{/if}

		{#if selectedPlanArchived && mode === 'single'}
			<p class="col-span-2 text-[10px] font-mono text-destructive">아카이브된 Plan은 실행할 수 없습니다.</p>
		{/if}

		<div class="flex items-center gap-2">
			<label for="mode-select" class="text-xs text-muted-foreground">Mode</label>
			<select
				id="mode-select"
				class="h-8 w-[120px] rounded-md border border-border bg-card px-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary"
				bind:value={mode}
			>
				<option value="single">단일 Plan</option>
				<option value="all">전체 실행</option>
			</select>
		</div>

		<div class="flex items-center gap-2">
			<label for="engine-select" class="text-xs text-muted-foreground">Engine</label>
			<select
				id="engine-select"
				class={`h-8 w-[112px] rounded-md border border-border px-2 text-xs font-mono font-medium focus:outline-none focus:ring-2 focus:ring-primary ${getEngineThemeClasses(selectedEngine)}`}
				bind:value={selectedEngine}
			>
				{#each getEngineOptions() as engine}
					<option value={engine}>{formatEngineLabel(engine)}</option>
				{/each}
			</select>
		</div>

		<div class="flex items-center gap-1">
			<span class="text-[10px] font-medium text-muted-foreground">Fix</span>
			<select
				class={`h-8 w-[112px] rounded-md border border-border px-2 text-xs font-mono font-medium focus:outline-none focus:ring-2 focus:ring-primary ${getEngineThemeClasses(selectedFixEngine)}`}
				bind:value={selectedFixEngine}
			>
				{#each getEngineOptions() as engine}
					<option value={engine}>{formatEngineLabel(engine)}</option>
				{/each}
			</select>
		</div>

		{#if showProfileSelect}
			<div class="flex items-center gap-1">
				<span class="text-[10px] font-medium text-muted-foreground">Profile</span>
				<select
					class={`h-8 w-[100px] rounded-md border border-border px-2 text-xs font-mono font-medium focus:outline-none focus:ring-2 focus:ring-primary ${getEngineThemeClasses(selectedEngine)}`}
					bind:value={selectedProfile}
				>
					{#each profilesForEngine as profile}
						<option value={profile.name}>{profile.name}</option>
					{/each}
				</select>
			</div>
		{/if}

		{#if runningEngine}
			<span class={`inline-flex h-7 items-center rounded border px-2 text-[10px] font-mono ${getEngineThemeClasses(runningEngine)}`}>
				Run {formatEngineLabel(runningEngine)}
			</span>
		{/if}
	</div>

	{#if selectedEngineConfig}
		<div class="col-span-2 space-y-2">
			<button
				type="button"
				class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
				onclick={() => { advancedOpen = !advancedOpen; }}
			>
				<span>Phase Models</span>
				{#if advancedOpen}
					<ChevronUp class="h-3 w-3" />
				{:else}
					<ChevronDown class="h-3 w-3" />
				{/if}
			</button>

			{#if advancedOpen}
				<div class="rounded-md border border-border bg-card p-3 space-y-2">
					{#each selectedEnginePhases as phase, index}
						<div class="flex items-center justify-between gap-3">
							<label
								for={getPhaseSelectId(phase, index)}
								class="text-[10px] font-mono uppercase text-muted-foreground w-20 shrink-0"
							>{phase}</label>
							<select
								id={getPhaseSelectId(phase, index)}
								class="border rounded px-1.5 py-0.5 flex-1 h-7 text-[10px] font-mono bg-card"
								value={getPhaseModel(phase)}
								onchange={(e) => onUpdateModel(phase, e.currentTarget.value)}
							>
								{#each selectedEngineModelOptions as model}
									<option value={model}>{model}</option>
								{/each}
								{#if !selectedEngineModelOptions.includes(getPhaseModel(phase))}
									<option value={getPhaseModel(phase)}>{getPhaseModel(phase)} (Custom)</option>
								{/if}
							</select>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

		<div class="col-span-2 flex flex-wrap items-center gap-x-6 gap-y-2 pt-1 text-xs">
			<div class="flex items-center gap-2">
				<label for="max-cycles" class="text-xs text-muted-foreground">Max Cycles</label>
				<input
					id="max-cycles"
					type="number"
					class="h-8 w-16 rounded-md border border-border bg-card px-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary"
					bind:value={maxCycles}
					min="0"
					placeholder="∞"
				/>
				<label for="end-time" class="text-xs text-muted-foreground">End Time</label>
				<input
					id="end-time"
					type="time"
					class="h-8 w-24 rounded-md border border-border bg-card px-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-primary"
					bind:value={until}
				/>
			</div>

			<div class="flex items-center gap-2">
				<label class="relative inline-flex items-center cursor-pointer scale-90">
					<input type="checkbox" bind:checked={dryRun} class="sr-only peer" />
					<div class="w-8 h-4 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-card after:border-border after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-primary"></div>
				</label>
				<span class="text-xs text-muted-foreground flex items-center gap-1">
					Dry Run
				</span>
			</div>

			<div class="flex items-center gap-2">
				<label class="relative inline-flex items-center cursor-pointer scale-90">
					<input type="checkbox" bind:checked={worktree} class="sr-only peer" />
					<div class="w-8 h-4 bg-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-card after:border-border after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-success"></div>
				</label>
				<span class="text-xs text-muted-foreground">Worktree 모드</span>
			</div>

			{#if mode === 'single'}
				<label class="flex items-center gap-1.5 cursor-pointer text-xs text-muted-foreground">
					<input type="checkbox" bind:checked={parallel} class="rounded" />
					<span>병렬</span>
				</label>
			{/if}
		</div>

	{#if (mode === 'single' && parallel) || mode === 'all'}
		<div class="col-span-2 flex items-center gap-2 text-xs">
			<label class="shrink-0 text-muted-foreground" for="projects-input">프로젝트:</label>
			<input
				id="projects-input"
				type="text"
				class="h-8 flex-1 rounded-md border border-border bg-card px-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary"
				bind:value={projects}
				placeholder="쉼표 구분 (비우면 전체)"
			/>
		</div>
	{/if}
</div>
