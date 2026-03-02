<script lang="ts">
	interface RunnerTab {
		id: string;
		plan_file: string | null;
		engine: string | null;
		running: boolean;
		start_time: string | null;
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
		onSync?: () => void;
		onReset?: () => void;
		onExecute?: () => void;
	}

	let {
		runners,
		sseConnected,
		runStatus,
		elapsed,
		onStopAll,
		onSync,
		onReset,
		onExecute,
	}: Props = $props();

	let runningCount = $derived(runners.filter(r => r.running).length);
	let anyRunning = $derived(runningCount > 0);
	let anyCrashed = $derived(!anyRunning && !!runStatus?.crashed);
</script>

<div class="flex items-center justify-between px-3 py-2 border-b bg-white shrink-0">
	<!-- 좌측: 연결 상태 + runner 상태 + elapsed -->
	<div class="flex items-center gap-3 min-w-0">
		<!-- SSE 연결 상태 dot -->
		<div class="flex items-center gap-1.5 shrink-0">
			{#if sseConnected}
				<div class="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
			{:else}
				<div class="w-1.5 h-1.5 rounded-full bg-gray-300 animate-pulse"></div>
			{/if}
		</div>

		<!-- Runner 상태 dots -->
		{#if runners.length > 0}
			<div class="flex items-center gap-1 shrink-0">
				{#each runners as runner (runner.id)}
					{#if runner.running}
						<div class="dr-pulse-dot bg-green-500" title="{runner.plan_file?.split(/[\\/]/).pop() ?? '전체 실행'} - 실행 중"></div>
					{:else}
						<div class="w-2 h-2 rounded-full bg-gray-300" title="{runner.plan_file?.split(/[\\/]/).pop() ?? '전체 실행'} - 중지"></div>
					{/if}
				{/each}
			</div>
		{/if}

		<!-- 상태 텍스트 -->
		<div class="flex items-center gap-2 text-xs shrink-0">
			{#if anyRunning}
				<span class="font-medium text-green-700">실행 중</span>
				{#if runningCount > 1}
					<span class="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">{runningCount}개</span>
				{/if}
				<span class="text-gray-400 font-mono">{elapsed}</span>
			{:else if anyCrashed}
				<span class="font-medium text-red-600">비정상 종료</span>
			{:else}
				<span class="text-gray-500">대기</span>
			{/if}
		</div>
	</div>

	<!-- 우측: 액션 버튼들 -->
	<div class="flex items-center gap-1 shrink-0">
		{#if onSync}
			<button
				onclick={onSync}
				class="px-2 py-1 text-[11px] font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
				title="Plan 동기화"
			>
				Sync
			</button>
		{/if}

		{#if onReset}
			<button
				onclick={onReset}
				class="px-2 py-1 text-[11px] font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
				title="상태 초기화"
			>
				Reset
			</button>
		{/if}

		{#if anyRunning && onStopAll}
			<button
				onclick={onStopAll}
				class="px-2 py-1 text-[11px] font-medium text-red-600 hover:text-red-700 hover:bg-red-50 rounded transition-colors"
				title="모두 정지"
			>
				Stop
			</button>
		{/if}

		{#if onExecute}
			<button
				onclick={onExecute}
				class="px-2.5 py-1 text-[11px] font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded transition-colors"
				title="실행"
			>
				Execute
			</button>
		{/if}
	</div>
</div>
