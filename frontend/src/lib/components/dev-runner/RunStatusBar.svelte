<script lang="ts">
	import DevRunnerSettingsPanel from './DevRunnerSettingsPanel.svelte';

	interface RunnerTab {
		id: string;
		plan_file: string | null;
		engine: string | null;
		running: boolean;
		start_time: string | null;
		branch?: string | null;
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
		onReset?: () => void;
		onExecute?: () => void;
		onStopRunner?: (id: string) => void;
		onKillRunner?: (id: string) => void;
	}

	let {
		runners,
		sseConnected,
		runStatus,
		elapsed,
		onStopAll,
		onForceStop,
		onSync,
		onReset,
		onExecute,
		onStopRunner,
		onKillRunner,
	}: Props = $props();

	let runningCount = $derived(runners.filter(r => r.running).length);
	let anyRunning = $derived(runningCount > 0);
	let anyCrashed = $derived(!anyRunning && !!runStatus?.crashed);
	let showSettings = $state(false);
</script>

<div class="bg-card border border-border rounded-md shrink-0 overflow-hidden">
	<!-- 상단 바: 연결 상태 + runner 상태 + elapsed + 액션 버튼 -->
	<div class="flex items-center justify-between px-3 py-1.5">
		<!-- 좌측: 연결 상태 + runner 상태 + elapsed -->
		<div class="flex items-center gap-3 min-w-0">
			<!-- SSE 연결 상태 dot -->
			<div class="flex items-center gap-1.5 shrink-0">
				{#if sseConnected}
					<div class="pulse-dot bg-status-running"></div>
				{:else}
					<div class="pulse-dot bg-status-failed animate-pulse"></div>
				{/if}
			</div>

			<!-- Runner 상태 dots -->
			{#if runners.length > 0}
				<div class="flex items-center gap-1 shrink-0">
					{#each runners as runner (runner.id)}
						{#if runner.running}
							<div class="pulse-dot bg-status-running" title="{runner.plan_file?.split(/[\\/]/).pop() ?? '전체 실행'} - 실행 중"></div>
						{:else}
							<div class="w-2 h-2 rounded-full bg-muted-foreground/30" title="{runner.plan_file?.split(/[\\/]/).pop() ?? '전체 실행'} - 중지"></div>
						{/if}
					{/each}
				</div>
			{/if}

			<!-- Zap 아이콘 + runner count + elapsed -->
			<div class="flex items-center gap-1.5 shrink-0">
				<!-- Zap SVG 아이콘 -->
				<svg class="w-3.5 h-3.5 text-primary" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
				</svg>
				<span class="font-mono font-semibold text-xs">
					{runningCount} runner{runningCount !== 1 ? 's' : ''}
				</span>
				{#if anyRunning && elapsed}
					<span class="text-[10px] font-mono text-muted-foreground">{elapsed}</span>
				{/if}
			</div>
		</div>

		<!-- 우측: 액션 버튼들 (아이콘 전용 ghost) -->
		<div class="flex items-center gap-0.5 shrink-0 relative">
			{#if anyRunning && onStopAll}
				<button
					onclick={onStopAll}
					class="h-6 w-6 flex items-center justify-center text-destructive rounded-md hover:bg-secondary transition-colors"
					title="Stop all"
				>
					<!-- Square icon -->
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" viewBox="0 0 24 24" fill="currentColor">
						<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
					</svg>
				</button>
			{/if}

			{#if onForceStop}
				<button
					onclick={onForceStop}
					class="h-6 w-6 flex items-center justify-center rounded-md hover:bg-secondary transition-colors"
					title="Force stop"
				>
					<!-- Power icon -->
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>
						<line x1="12" y1="2" x2="12" y2="12"/>
					</svg>
				</button>
			{/if}

			{#if onSync}
				<button
					onclick={onSync}
					class="h-6 w-6 flex items-center justify-center rounded-md hover:bg-secondary transition-colors"
					title="Sync"
				>
					<!-- RefreshCw icon -->
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<polyline points="23 4 23 10 17 10"/>
						<polyline points="1 20 1 14 7 14"/>
						<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
					</svg>
				</button>
			{/if}

			{#if onReset}
				<button
					onclick={onReset}
					class="h-6 w-6 flex items-center justify-center rounded-md hover:bg-secondary transition-colors"
					title="Full reset"
				>
					<!-- RotateCcw icon -->
					<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<polyline points="1 4 1 10 7 10"/>
						<path d="M3.51 15a9 9 0 1 0 .49-3.51"/>
					</svg>
				</button>
			{/if}

			<!-- 설정 버튼 + 팝오버 -->
			<div class="relative">
				<button
					onclick={() => showSettings = !showSettings}
					class="px-2 py-1 text-[11px] font-medium text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded transition-colors {showSettings ? 'bg-gray-100 text-gray-800' : ''}"
					title="설정"
				>
					⚙
				</button>
				{#if showSettings}
					<div class="absolute right-0 top-full mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg w-64">
						<DevRunnerSettingsPanel compact />
					</div>
				{/if}
			</div>

			{#if onExecute}
				<button
					onclick={onExecute}
					class="px-2.5 py-1 text-[11px] font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors"
					title="실행"
				>
					Execute
				</button>
			{/if}
		</div>
	</div>

	<!-- Runner 목록 행 (runner가 1개 이상일 때) -->
	{#if runners.length > 0}
		<div class="divide-y divide-border">
			{#each runners as runner (runner.id)}
				<div class="flex items-center gap-2 px-3 py-1.5 text-xs group hover:bg-secondary/50">
					<!-- 상태 dot -->
					{#if runner.running}
						<div class="pulse-dot bg-status-running shrink-0"></div>
					{:else}
						<div class="w-1.5 h-1.5 rounded-full bg-muted-foreground shrink-0"></div>
					{/if}

					<!-- plan 파일명 -->
					<span class="truncate flex-1 min-w-0 font-mono text-[11px] text-foreground" title={runner.plan_file ?? ''}>
						{runner.plan_file ? runner.plan_file.split(/[/\\]/).pop() : '전체 실행'}
					</span>

					<!-- engine (sm 이상) -->
					{#if runner.engine}
						<span class="hidden sm:block text-[10px] text-muted-foreground shrink-0 font-mono">{runner.engine}</span>
					{/if}

					<!-- worktree branch (md 이상) -->
					{#if runner.branch}
						<span class="hidden md:block text-[10px] text-muted-foreground shrink-0 font-mono truncate max-w-[120px]" title={runner.branch}>{runner.branch}</span>
					{/if}

					<!-- Stop/Kill 아이콘 버튼 (hover 시 표시) -->
					<div class="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
						{#if runner.running && onStopRunner}
							<button
								onclick={() => onStopRunner?.(runner.id)}
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
								onclick={() => onKillRunner?.(runner.id)}
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
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
