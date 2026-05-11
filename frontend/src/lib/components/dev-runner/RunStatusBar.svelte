<script lang="ts">
	import {
		ChevronDown,
		ChevronUp,
		Play,
		Power,
		RefreshCw,
		RotateCcw,
		Settings,
		Square,
		Terminal,
		Trash2,
		X
	} from 'lucide-svelte';
	import DevRunnerSettingsPanel from './DevRunnerSettingsPanel.svelte';
	import { getExitReasonDisplay } from '$lib/utils/dev-runner-exit-reason';

	interface RunnerTab {
		id: string;
		plan_file: string | null;
		engine: string | null;
		running: boolean;
		start_time: string | null;
		branch?: string | null;
		merge_status?: string | null;
		exit_reason?: string | null;
		display_plan_name?: string | null;
		worktree_exists?: boolean | 'unknown';
		branch_exists?: boolean | 'unknown';
		branch_merged_to_main?: boolean | 'unknown';
		metadata_checked_at?: string | null;
		display_label?: string | null;
		display_secondary?: string | null;
		hide_stale_branch_badge?: boolean;
		orphan_alive?: boolean;
		redis_missing?: boolean;
	}

	function resolveFullLabel(runner: RunnerTab): string {
		if (runner.plan_file) {
			if (runner.plan_file === '__ALL_PLANS__' || runner.plan_file === 'ALL') return '전체 실행';
			return runner.plan_file.split(/[/\\]/).pop() ?? runner.plan_file;
		}
		return runner.display_plan_name ?? '(알 수 없음)';
	}

	function resolveRunnerLabel(runner: RunnerTab, index: number): string {
		const fullLabel = resolveFullLabel(runner);
		if (fullLabel && fullLabel !== '(알 수 없음)') return fullLabel;
		return `Runner ${index + 1}`;
	}

	function resolveRunnerStateTitle(runner: RunnerTab): string {
		if (runner.display_label) return runner.display_label;
		if (runner.running) return 'running';
		if (runner.merge_status === 'error') return '머지 오류';
		if (runner.merge_status === 'conflict') return '충돌';
		if (runner.merge_status === 'test_failed') return '테스트 실패';
		const exitDisplay = getExitReasonDisplay(runner.exit_reason);
		return runner.exit_reason ? `${exitDisplay.statusIcon} (${runner.exit_reason})` : exitDisplay.statusIcon;
	}

	function resolveStaleLabel(runner: RunnerTab): string | null {
		if (runner.hide_stale_branch_badge) return null;
		return runner.display_secondary ?? null;
	}

	function resolveMetaTitle(runner: RunnerTab, index: number): string {
		const rows = [
			`runner: ${runner.id}`,
			`index: Runner ${index + 1}`,
			`label: ${resolveRunnerLabel(runner, index)}`,
			`state: ${resolveRunnerStateTitle(runner)}`,
			runner.plan_file ? `file: ${runner.plan_file}` : null,
			runner.engine ? `engine: ${runner.engine}` : null,
			runner.branch ? `branch: ${runner.branch}` : null,
			`worktree_exists: ${runner.worktree_exists ?? 'unknown'}`,
			`branch_exists: ${runner.branch_exists ?? 'unknown'}`,
			`branch_merged_to_main: ${runner.branch_merged_to_main ?? 'unknown'}`,
			`metadata_checked_at: ${runner.metadata_checked_at ?? 'unknown'}`,
		];
		return rows.filter(Boolean).join('\n');
	}

	interface RunStatus {
		running: boolean;
		crashed?: boolean;
	}

	interface Props {
		runners: RunnerTab[];
		sseConnected: boolean;
		runStatus: RunStatus | null;
		elapsed: string;
		onStopAll?: () => void;
		onForceStop?: () => void;
		onSync?: () => void;
		onCleanup?: () => void;
		onReset?: () => void;
		onExecute?: () => void;
		onStopRunner?: (id: string) => void;
		onKillRunner?: (id: string) => void;
		onCloseRunner?: (id: string) => void;
		collapsed?: boolean;
		onToggleCollapse?: () => void;
		onSelectRunner?: (id: string) => void;
		onCloseAllTerminated?: () => void;
		activeRunnerId?: string | null;
		onShowLogs?: () => void;
	}

	let {
		runners,
		sseConnected,
		runStatus,
		elapsed,
		onStopAll,
		onForceStop,
		onSync,
		onCleanup,
		onReset,
		onExecute,
		onStopRunner,
		onKillRunner,
		onCloseRunner,
		collapsed = false, onToggleCollapse, onSelectRunner, onCloseAllTerminated, activeRunnerId = null, onShowLogs,
	}: Props = $props();

	let runningCount = $derived(runners.filter(r => r.running).length);
	let orphanCount = $derived(runners.filter(r => r.orphan_alive || r.redis_missing).length);
	let anyRunning = $derived(runningCount > 0);
	let anyCrashed = $derived(!anyRunning && !!runStatus?.crashed);
	let stoppedCount = $derived(runners.length - runningCount);
	let activeRunner = $derived(runners.find(r => r.id === activeRunnerId) ?? null);
	let activeRunnerIndex = $derived(activeRunner ? runners.findIndex(r => r.id === activeRunner.id) : -1);
	let activeRunnerLabel = $derived(activeRunner && activeRunnerIndex >= 0 ? `Selected ${resolveRunnerLabel(activeRunner, activeRunnerIndex)}` : null);
	let activeRunnerMetaTitle = $derived(activeRunner && activeRunnerIndex >= 0 ? resolveMetaTitle(activeRunner, activeRunnerIndex) : '');
	let summaryText = $derived(
		`${sseConnected ? 'Online' : 'Offline'} · ${runningCount}/${runners.length} active${anyRunning && elapsed ? ` · ${elapsed}` : ''}`
	);
	let showSettings = $state(false);
	let showSecondaryActions = $state(false);
</script>

<div class="bg-card border border-border rounded-md shrink-0 overflow-hidden">
	<!-- 상단 바: compact summary + primary actions -->
	<div class="flex min-h-9 items-center justify-between gap-2 px-3 py-1">
		<div class="flex min-w-0 items-center gap-2">
			<div
				class="h-2 w-2 shrink-0 rounded-full {sseConnected ? 'bg-status-running' : 'bg-status-failed animate-pulse'}"
				title={sseConnected ? 'SSE 연결됨' : 'SSE 연결 끊김'}
			></div>
			<div class="min-w-0">
				<div class="flex min-w-0 items-center gap-2">
					<span class="truncate text-xs font-semibold text-foreground">{summaryText}</span>
					{#if stoppedCount > 0}
						<span class="hidden rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline-flex">
							{stoppedCount} stopped
						</span>
					{/if}
					{#if orphanCount > 0}
						<span class="hidden rounded bg-orange-100 px-1.5 py-0.5 text-[10px] text-orange-700 sm:inline-flex">
							{orphanCount} orphan
						</span>
					{/if}
				</div>
				{#if activeRunnerLabel}
					<div class="hidden truncate text-[10px] font-mono text-muted-foreground md:block" title={activeRunnerMetaTitle}>
						{activeRunnerLabel}
					</div>
				{/if}
			</div>
		</div>

		<!-- 우측: primary actions + secondary overflow -->
		<div class="flex items-center gap-0.5 shrink-0 relative">
			{#if anyRunning && onStopAll}
				<button
					onclick={onStopAll}
					class="h-6 w-6 flex items-center justify-center text-destructive rounded-md hover:bg-secondary transition-colors"
					title="Stop all"
				>
					<Square size={13} fill="currentColor" />
				</button>
			{/if}

			{#if onShowLogs}
				<button
					onclick={onShowLogs}
					class="h-6 w-6 flex items-center justify-center rounded-md hover:bg-secondary transition-colors text-muted-foreground"
					title="통합 로그"
				>
					<Terminal size={13} />
				</button>
			{/if}

			<button
				onclick={() => { showSecondaryActions = !showSecondaryActions; showSettings = false; }}
				class="h-6 w-6 flex items-center justify-center rounded-md hover:bg-secondary transition-colors text-muted-foreground {showSecondaryActions ? 'bg-secondary text-foreground' : ''}"
				title="보조 작업"
				aria-expanded={showSecondaryActions}
			>
				<Settings size={13} />
			</button>

			{#if runners.length > 0 && onToggleCollapse}
				<button
					onclick={onToggleCollapse}
					class="h-6 w-6 flex items-center justify-center rounded-md hover:bg-secondary transition-colors text-muted-foreground"
					title={collapsed ? '펼치기' : '접기'}
				>
					{#if collapsed}
						<ChevronDown size={13} />
					{:else}
						<ChevronUp size={13} />
					{/if}
				</button>
			{/if}

			{#if onExecute}
				<button
					onclick={onExecute}
					class="inline-flex h-7 items-center gap-1 rounded-md bg-blue-600 px-2 text-[11px] font-semibold text-white transition-colors hover:bg-blue-700"
					title="실행"
				>
					<Play size={12} fill="currentColor" />
					<span class="hidden sm:inline">Run</span>
				</button>
			{/if}

			{#if showSecondaryActions}
				<div class="absolute right-0 top-full z-50 mt-1 w-64 rounded-md border border-border bg-popover p-1.5 text-popover-foreground shadow-lg">
					<div class="grid grid-cols-2 gap-1">
						{#if onForceStop}
							<button
								onclick={() => { onForceStop?.(); showSecondaryActions = false; }}
								class="inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs hover:bg-secondary"
							>
								<Power size={13} /> Force stop
							</button>
						{/if}
						{#if onSync}
							<button
								onclick={() => { onSync?.(); showSecondaryActions = false; }}
								class="inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs hover:bg-secondary"
							>
								<RefreshCw size={13} /> Sync
							</button>
						{/if}
						{#if onCleanup}
							<button
								onclick={() => { onCleanup?.(); showSecondaryActions = false; }}
								class="inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs hover:bg-secondary"
							>
								<Trash2 size={13} /> Cleanup
							</button>
						{/if}
						{#if onReset}
							<button
								onclick={() => { onReset?.(); showSecondaryActions = false; }}
								class="inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs hover:bg-secondary"
							>
								<RotateCcw size={13} /> Reset
							</button>
						{/if}
						{#if stoppedCount > 0 && onCloseAllTerminated}
							<button
								onclick={() => { onCloseAllTerminated?.(); showSecondaryActions = false; }}
								class="inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs text-destructive hover:bg-secondary"
							>
								<X size={13} /> Close stopped
							</button>
						{/if}
						<button
							onclick={() => { showSettings = !showSettings; }}
							class="inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs hover:bg-secondary {showSettings ? 'bg-secondary' : ''}"
						>
							<Settings size={13} /> Settings
						</button>
					</div>
					{#if showSettings}
						<div class="mt-1 border-t border-border pt-1">
							<DevRunnerSettingsPanel compact />
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>

	<!-- Runner 목록 행 (runner가 1개 이상일 때) -->
	{#if runners.length > 0 && !collapsed}
		<div class="divide-y divide-border overflow-y-auto" style="max-height: 5.25rem;">
			{#each runners as runner, index (runner.id)}
				<div
				class="flex items-center gap-2 px-3 py-1.5 text-xs group hover:bg-secondary/50 cursor-pointer {activeRunnerId === runner.id ? 'bg-primary/10' : ''}"
				onclick={() => onSelectRunner?.(runner.id)}
				role="button"
				tabindex="0"
				onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelectRunner?.(runner.id); }}
				title={resolveMetaTitle(runner, index)}
			>
					<!-- 상태 dot -->
					{#if runner.running}
						<div class="pulse-dot bg-status-running shrink-0" title="running"></div>
					{:else if runner.merge_status === 'error'}
						<div class="w-1.5 h-1.5 rounded-full bg-status-failed shrink-0" title={resolveRunnerStateTitle(runner)}></div>
					{:else if runner.merge_status === 'conflict' || runner.merge_status === 'test_failed'}
						<div class="w-1.5 h-1.5 rounded-full bg-status-failed shrink-0" title={resolveRunnerStateTitle(runner)}></div>
					{:else if runner.merge_status === 'approval_required'}
						<div class="w-1.5 h-1.5 rounded-full bg-status-queued shrink-0" title={resolveRunnerStateTitle(runner)}></div>
					{:else}
						{@const exitDisplay = getExitReasonDisplay(runner.exit_reason)}
						<div class="w-1.5 h-1.5 rounded-full {exitDisplay.dotClass} shrink-0" title={resolveRunnerStateTitle(runner)}></div>
					{/if}

					<!-- 계획서 파일명 중심 라벨. runner id/index/branch는 title에 보조 노출한다. -->
					<span class="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground">
						{resolveRunnerLabel(runner, index)}
					</span>

					<!-- engine (sm 이상) -->
					{#if runner.engine}
						<span class="hidden sm:block text-[10px] text-muted-foreground shrink-0 font-mono">{runner.engine}</span>
					{/if}

					{#if resolveStaleLabel(runner)}
						<span class="hidden shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground md:inline-flex">
							{resolveStaleLabel(runner)}
						</span>
					{/if}

					<!-- Stop/Kill/Close 아이콘 버튼 -->
					{#if runner.running}
						<!-- 실행 중: hover 시만 표시 -->
						<div class="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
							{#if onStopRunner}
								<button
									onclick={(e) => { e.stopPropagation(); onStopRunner?.(runner.id); }}
									class="h-5 w-5 flex items-center justify-center rounded-md hover:bg-secondary transition-colors"
									title="정지"
								>
									<!-- Square icon -->
									<svg xmlns="http://www.w3.org/2000/svg" class="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
										<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
									</svg>
								</button>
							{/if}
							{#if onKillRunner}
								<button
									onclick={(e) => { e.stopPropagation(); onKillRunner?.(runner.id); }}
									class="h-5 w-5 flex items-center justify-center rounded-md hover:bg-secondary transition-colors text-destructive"
									title="강제 종료"
								>
									<!-- Power icon -->
									<svg xmlns="http://www.w3.org/2000/svg" class="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
										<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>
										<line x1="12" y1="2" x2="12" y2="12"/>
									</svg>
								</button>
							{/if}
							{#if onCloseRunner}
								<button
									onclick={(e) => { e.stopPropagation(); onCloseRunner?.(runner.id); }}
									class="h-5 w-5 flex items-center justify-center rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-destructive"
									title="닫기"
								>
									<!-- X icon -->
									<svg xmlns="http://www.w3.org/2000/svg" class="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
										<line x1="18" y1="6" x2="6" y2="18"/>
										<line x1="6" y1="6" x2="18" y2="18"/>
									</svg>
								</button>
							{/if}
						</div>
					{:else if onCloseRunner}
						<!-- 종료된 러너: 닫기 버튼 항상 표시 (모바일 대응) -->
						<button
							onclick={(e) => { e.stopPropagation(); onCloseRunner?.(runner.id); }}
							class="h-5 w-5 flex items-center justify-center rounded-md hover:bg-secondary transition-colors text-muted-foreground hover:text-destructive shrink-0"
							title="닫기"
						>
							<!-- X icon -->
							<svg xmlns="http://www.w3.org/2000/svg" class="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<line x1="18" y1="6" x2="6" y2="18"/>
								<line x1="6" y1="6" x2="18" y2="18"/>
							</svg>
						</button>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
