<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerLogApi } from '$lib/api';

	interface Props {
		runnerId: string;
		planFile?: string;
		currentPlanName?: string;
		running?: boolean;
		mergeStatus?: string | null;
		onBatchPlansChange?: (plans: BatchPlanItem[]) => void;
	}

	let { runnerId, planFile, currentPlanName, running = false, mergeStatus = null, onBatchPlansChange }: Props = $props();

	// 머지 진행 중 상태 판별
	let isMerging = $derived(
		mergeStatus === 'merge_pending' || mergeStatus === 'merging' || mergeStatus === 'testing'
	);

	// Phase 2: 전체실행 시 Plan 파일 리스트 추적
	interface BatchPlanItem {
		name: string;
		status: 'pending' | 'running' | 'done';
	}
	let batchPlans = $state<BatchPlanItem[]>([]);
	let batchDoneCount = $derived(batchPlans.filter(p => p.status === 'done').length);

	interface ParsedLine {
		timestamp: string;
		tag: string;
		message: string;
		raw: string;
		isStale: boolean;
		noiseCount?: number;
	}

	let lines = $state<ParsedLine[]>([]);
	let expandedNoiseIndices = $state<number[]>([]);
        let showNoiseIndicator = $state(false);
        let noiseTimer: ReturnType<typeof setTimeout> | null = null;
	let connected = $state<'connected' | 'disconnected'>('disconnected');
	let autoScroll = $state(true);
	let paused = $state(false);
	let pauseBuffer = $state<ParsedLine[]>([]);
	let logContainer: HTMLDivElement;
	let eventSource: EventSource | null = null;
	let sseStarted = $state(false);
	let reconnectCount = $state(0);
	let consecutiveErrors = $state(0);
	let redisAvailable = $state(true);
	let pendingStale = $state(false);
	let completedBanner = $state(false); // runner 정상 완료 배너
	const MAX_LINES = 500;
	let resultQueue: ParsedLine[] = [];
	let resultDrainInterval: ReturnType<typeof setInterval> | null = null;
	const SEPARATOR_PATTERN = '════════════════';

	const BASE_DELAY = 3000;

	// Tag colors for dark background
	const tagColors: Record<string, { text: string; bg: string }> = {
		AI: { text: 'text-blue-400', bg: 'bg-blue-500/20' },
		TOOL: { text: 'text-yellow-700', bg: 'bg-yellow-900/20' },
		DONE: { text: 'text-green-400', bg: 'bg-green-500/20' },
		RESULT: { text: 'text-emerald-700', bg: 'bg-emerald-900/20' },
		ERROR: { text: 'text-red-400', bg: 'bg-red-500/20' },
		INFO: { text: 'text-gray-500', bg: 'bg-transparent' },
		SYSTEM: { text: 'text-purple-400', bg: 'bg-purple-500/20' },
		WARN: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
		STDERR: { text: 'text-red-400', bg: 'bg-red-500/30' },
		LINE: { text: 'text-gray-600', bg: 'bg-transparent' },
		DIAG: { text: 'text-cyan-400', bg: 'bg-cyan-500/20' },
		THINK: { text: 'text-violet-400', bg: 'bg-violet-500/20' },
		PHASE: { text: 'text-indigo-400', bg: 'bg-indigo-500/20' },
		TRACK: { text: 'text-purple-400', bg: 'bg-purple-500/20' },
		CYCLE: { text: 'text-white', bg: 'bg-gray-600' },
		MERGE: { text: 'text-teal-400', bg: 'bg-teal-500/20' },
		COMMIT: { text: 'text-green-400', bg: 'bg-green-500/20' },
		TEST: { text: 'text-cyan-400', bg: 'bg-cyan-500/20' },
		SKIP: { text: 'text-gray-500', bg: 'bg-gray-500/20' },
		GIT: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
		BATCH: { text: 'text-teal-400', bg: 'bg-teal-500/20' },
		NOISE: { text: 'text-gray-600', bg: 'bg-gray-700/20' }
	};

	const LINE_PATTERN = /^\s*\[?(\d{2}:\d{2}:\d{2})\]?\s*\[(\w+)\]\s*(.*)/;
	const DIAG_PATTERN = /^\[(\w+)\]\s*(.*)/;
	const MERGE_TAG_PATTERN = /^\[MERGE\]\[(\w+)\]\s*(.*)/;

	function parseLine(text: string, isStale: boolean): ParsedLine {
		const match = text.match(LINE_PATTERN);
		if (match) {
			return { timestamp: match[1], tag: match[2], message: match[3], raw: text, isStale };
		}
		// [MERGE][TAG] message 형식 (머지 로그)
		const mergeMatch = text.match(MERGE_TAG_PATTERN);
		if (mergeMatch) {
			return { timestamp: '', tag: mergeMatch[1], message: mergeMatch[2], raw: text, isStale };
		}
		const diagMatch = text.match(DIAG_PATTERN);
		if (diagMatch) {
			const tag = diagMatch[1];
			const message = diagMatch[2];
			if (tag === 'NOISE') {
				const noiseCount = parseInt(message) || 0;
				return { timestamp: '', tag, message, raw: text, isStale, noiseCount };
			}
			return { timestamp: '', tag, message, raw: text, isStale };
		}
		return { timestamp: '', tag: '', message: text, raw: text, isStale };
	}

	function isSeparator(text: string): boolean {
		return text.includes(SEPARATOR_PATTERN);
	}

	function extractSeparatorText(text: string): string {
		return text.replace(/[═=\s]+/g, ' ').trim() || '새 세션';
	}

	function addLine(text: string, isStale: boolean) {
		// Phase 2: 그레이아웃 타이밍 변경 — 새 세션 시작 시에만 stale 마크
		if (text.includes(SEPARATOR_PATTERN) && !isStale) {
			if (pendingStale) {
				lines = lines.map((l) => ({ ...l, isStale: true }));
			}
			pendingStale = true;
		}

		const parsed = parseLine(text, isStale);

                if (parsed.tag === 'NOISE' && !isStale) {
                        showNoiseIndicator = true;
                        if (noiseTimer) { clearTimeout(noiseTimer); }
                        noiseTimer = setTimeout(() => { showNoiseIndicator = false; noiseTimer = null; }, 2000);
                } else if (!isStale) {
                        showNoiseIndicator = false;
                        if (noiseTimer) { clearTimeout(noiseTimer); noiseTimer = null; }
                }

                // BATCH 마커 감지 → 전체실행 파일 리스트 추적
		if (parsed.tag === 'BATCH' && !isStale) {
			const listMatch = parsed.message.match(/^PLAN_LIST\s+(.+)$/);
			if (listMatch) {
				batchPlans = listMatch[1].split(',').map(n => ({
					name: n.trim(),
					status: 'pending' as const
				}));
			}
			const startMatch = parsed.message.match(/^PLAN_START\s+(.+)$/);
			if (startMatch) {
				const name = startMatch[1].trim();
				batchPlans = batchPlans.map(p =>
					p.name === name ? { ...p, status: 'running' as const } : p
				);
			}
			const doneMatch = parsed.message.match(/^PLAN_DONE\s+(.+)$/);
			if (doneMatch) {
				const name = doneMatch[1].trim();
				batchPlans = batchPlans.map(p =>
					p.name === name ? { ...p, status: 'done' as const } : p
				);
			}
		}
		// SEPARATOR 감지 시 배치 리스트 초기화
		if (text.includes(SEPARATOR_PATTERN) && !isStale) {
			batchPlans = [];
		}

		if (paused && !isStale) {
			pauseBuffer.push(parsed);
			return;
		}

		// RESULT 라인(실시간)은 큐에 넣고 순차 출력
		if (parsed.tag === 'RESULT' && !isStale) {
			resultQueue.push(parsed);
			if (!resultDrainInterval) {
				resultDrainInterval = setInterval(() => {
					const next = resultQueue.shift();
					if (next) {
						pushLine(next);
					} else {
						clearInterval(resultDrainInterval!);
						resultDrainInterval = null;
					}
				}, 40);
			}
			return;
		}

		pushLine(parsed);
	}

	function pushLine(parsed: ParsedLine) {
		lines.push(parsed);
		if (lines.length > MAX_LINES) {
			lines = lines.slice(lines.length - MAX_LINES);
		}
		if (autoScroll && logContainer) {
			requestAnimationFrame(() => {
				if (logContainer) logContainer.scrollTop = logContainer.scrollHeight;
			});
		}
	}

	function resumeLog() {
		paused = false;
		if (pauseBuffer.length > 0) {
			for (const line of pauseBuffer) {
				lines.push(line);
			}
			pauseBuffer = [];
			if (lines.length > MAX_LINES) {
				lines = lines.slice(lines.length - MAX_LINES);
			}
			if (autoScroll && logContainer) {
				requestAnimationFrame(() => {
					if (logContainer) logContainer.scrollTop = logContainer.scrollHeight;
				});
			}
		}
	}

	function scrollToBottom() {
		if (logContainer) {
			logContainer.scrollTop = logContainer.scrollHeight;
			autoScroll = true;
		}
	}

	function handleScroll() {
		// 스크롤 위치는 추적하지만, autoScroll 해제는 Pause 버튼으로만
	}

	function getReconnectDelay() {
		return Math.min(BASE_DELAY * Math.pow(2, reconnectCount), 60000);
	}

	function manualReconnect() {
		reconnectCount = 0;
		if (lines.length <= 3) {
			void loadRecent();
		}
		connectSSE();
	}

	async function fetchStatus() {
		try {
			const statusRes = await fetch('/api/v1/dev-runner/status');
			if (statusRes.ok) {
				redisAvailable = true;
				await statusRes.json();
			} else {
				redisAvailable = false;
			}
		} catch {
			// API 서버 오프라인
		}
	}

	async function connectSSE() {
		if (eventSource) eventSource.close();
                        if (noiseTimer) clearTimeout(noiseTimer);

		// SSE 연결 전 status API로 실행 상태 + Redis 상태 확인
		await fetchStatus();

		eventSource = isMerging
			? devRunnerLogApi.connectMergeStream(runnerId)
			: devRunnerLogApi.connectStream(runnerId);
		eventSource.onopen = () => {
			connected = 'connected';
			sseStarted = true;
			reconnectCount = 0;
			consecutiveErrors = 0;
		};
		eventSource.onmessage = (event) => {
			addLine(event.data, false);
		};
		// Redis 연결 끊김 이벤트 처리
		eventSource.addEventListener('redis_disconnected', () => {
			redisAvailable = false;
		});
		// Redis 재연결 시 connected 이벤트로 복구
		eventSource.addEventListener('connected', () => {
			redisAvailable = true;
		});
		// runner 정상 완료 신호 — 배너 표시 후 재연결 중지
		eventSource.addEventListener('completed', () => {
			completedBanner = true;
			eventSource?.close();
			eventSource = null;
			connected = 'disconnected';
		});
		eventSource.onerror = async () => {
			// completed 후 eventSource가 닫혀서 발생한 error면 재연결 중지
			if (completedBanner) return;
			consecutiveErrors++;
			eventSource?.close();
			eventSource = null;

			connected = 'disconnected';
			reconnectCount++;
			await fetchStatus();
			setTimeout(connectSSE, getReconnectDelay());
		};
	}

	async function loadFull() {
		try {
			const res = await devRunnerLogApi.full(runnerId, 0, 500);
			if (res.lines.length > 0) {
				lines = res.lines.map((text: string) => parseLine(text, true));
			}
		} catch {
			// full 로그 없을 수 있음
		}
	}

	async function loadRecent() {
		try {
			const res = await devRunnerLogApi.recent(runnerId, 100);
			const parsed = res.lines.map((text: string) => parseLine(text, true));

			if (running) {
				// running 중이면 마지막 SEPARATOR 이후 구간은 현재 세션 → isStale: false
				const lastSepIdx = parsed.findLastIndex((l: ParsedLine) =>
					l.raw.includes(SEPARATOR_PATTERN)
				);
				if (lastSepIdx === -1) {
					// SEPARATOR 없으면 전체가 현재 세션
					parsed.forEach((l: ParsedLine) => (l.isStale = false));
				} else {
					// SEPARATOR 이후 줄만 현재 세션
					for (let i = lastSepIdx + 1; i < parsed.length; i++) {
						parsed[i].isStale = false;
					}
				}
			}

			lines = parsed;

			// 醫낅즺 runner 濡쒓렇 ?뚯씪 誘명깘吏 ??full ?붾뱶?ъ씤?몃줈 ?꾪솚
			const allMerge = parsed.length > 0 && parsed.every((l: ParsedLine) => l.tag === 'MERGE');
			if (!running && (parsed.length === 0 || allMerge)) {
				await loadFull();
			}

			// Phase 3: 로드된 lines에 SEPARATOR가 있으면 pendingStale = true로 초기화
			// → 다음 SSE SEPARATOR 수신 시 이전 로그를 정상적으로 grayout 처리하기 위함
			if (parsed.some((l: ParsedLine) => l.raw.includes(SEPARATOR_PATTERN))) {
				pendingStale = true;
			}
		} catch {
			// 로그 없을 수 있음
		}
	}

	async function runDiagnostics() {
		try {
			const diag = await devRunnerLogApi.diagnostics();
			for (const s of diag.steps) {
				const icon = s.ok ? '✓' : '✗';
				addLine(`[DIAG] ${s.step}. ${s.name} ... ${icon} ${s.detail}`, false);
			}
		} catch {
			addLine('[DIAG] 진단 API 호출 실패 (API 서버 미응답)', false);
		}
	}

	onMount(async () => {
		await runDiagnostics();
		await loadRecent();
		// 초기 로드 후 스크롤을 맨 아래로 이동
		requestAnimationFrame(() => scrollToBottom());
		connectSSE();
	});

	onDestroy(() => {
		if (eventSource) {
			eventSource.close();
                        if (noiseTimer) clearTimeout(noiseTimer);
			eventSource = null;
		}
		if (resultDrainInterval) {
			clearInterval(resultDrainInterval);
			resultDrainInterval = null;
		}
	});

	function getTagStyle(tag: string) {
		return tagColors[tag] ?? tagColors.INFO;
	}

	// batchPlans 변경 시 부모에 알림
	$effect(() => {
		onBatchPlansChange?.(batchPlans);
	});

	// mergeStatus 전환 시 SSE 재연결 (runner → merge stream 또는 반대)
	let prevMerging: boolean | undefined;
	$effect(() => {
		const cur = isMerging;
		if (prevMerging !== undefined && prevMerging !== cur) {
			addLine(cur ? '[MERGE] 머지 로그 스트림으로 전환...' : '[MERGE] 러너 로그 스트림으로 복귀...', false);
			connectSSE();
		}
		prevMerging = cur;
	});

</script>

<div class="flex flex-col h-full min-h-0">
	<!-- Toolbar -->
	<div class="flex items-center justify-between px-3 py-2 border-b border-border shrink-0 bg-gray-900">
		<div class="flex items-center gap-2">
			<span class="text-xs font-medium uppercase tracking-wider text-gray-300">Live Logs</span>
			<div class="flex items-center gap-1">
				<!-- SSE 상태 원 -->
				<div
					class="w-2 h-2 rounded-full {connected === 'connected' ? 'bg-green-500' : 'bg-gray-400 animate-pulse'}"
					title={connected === 'connected' ? 'SSE 연결됨' : `재연결 중... (${reconnectCount})`}
				></div>
				<!-- Redis 상태 원 (SSE 연결 시에만 표시) -->
				{#if connected === 'connected'}
					<div
						class="w-2 h-2 rounded-full {redisAvailable ? 'bg-green-500' : 'bg-yellow-500'}"
						title={redisAvailable ? 'Redis 연결됨' : 'Redis 미연결'}
					></div>
				{/if}
			</div>
		</div>
		<div class="flex items-center gap-1">
			{#if connected !== 'connected' || !redisAvailable}
				<button
					class="h-6 w-6 rounded transition-colors inline-flex items-center justify-center hover:bg-gray-700"
					title="재연결"
					onclick={manualReconnect}
				>
					<svg class="h-3 w-3 text-status-failed" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/><path d="M10.71 5.05A16 16 0 0 1 22.56 9"/><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
				</button>
			{/if}
			<button
				class="relative h-6 w-6 rounded transition-colors inline-flex items-center justify-center {autoScroll ? 'text-primary' : 'text-muted-foreground'} hover:bg-gray-700"
				title={autoScroll ? 'Pin (auto-scroll on)' : 'Unpin (auto-scroll off)'}
				onclick={() => {
					if (autoScroll) {
						autoScroll = false;
						paused = true;
					} else {
						resumeLog();
						scrollToBottom();
					}
				}}
			>
				{#if autoScroll}
					<!-- Pin icon -->
					<svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg>
				{:else}
					<!-- PinOff icon -->
					<svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="2" y1="2" x2="22" y2="22"/><line x1="12" y1="17" x2="12" y2="22"/><path d="M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17h12"/><path d="M15 9.34V6h1a2 2 0 0 0 0-4H7.89"/></svg>
					{#if pauseBuffer.length > 0}
						<span class="absolute -top-1 -right-1 bg-primary text-primary-foreground text-[9px] font-bold rounded-full min-w-[14px] h-[14px] flex items-center justify-center px-0.5 leading-none">
							{pauseBuffer.length}
						</span>
					{/if}
				{/if}
			</button>
		</div>
	</div>

	{#if completedBanner}
		<div class="px-3 py-1.5 bg-green-900/40 border-b border-green-700/50 text-xs text-green-300 shrink-0 flex items-center gap-2">
			<span>✅ 실행 완료 — 로그 파일에서 계속 볼 수 있습니다</span>
		</div>
	{/if}

	<!-- Log Content (Phase 2: text-sm for body) -->
	<div
		bind:this={logContainer}
		onscroll={handleScroll}
		class="flex-1 min-h-0 overflow-y-auto font-mono text-sm p-3 bg-gray-950 text-gray-300 dr-scrollbar-thin"
	>
		{#if lines.length === 0}
			<span class="text-gray-600">로그가 없습니다</span>
		{:else}
			{#each lines as line, i}
				{#if line.tag === 'NOISE'}
					<div class="py-0.5 leading-5">
						{#if expandedNoiseIndices.includes(i)}
							<span class="text-gray-600 text-xs italic">[NOISE] {line.noiseCount} lines suppressed</span>
							<button
								onclick={() => expandedNoiseIndices = expandedNoiseIndices.filter(n => n !== i)}
								class="ml-1 text-gray-700 hover:text-gray-500 text-xs"
							>▲</button>
						{:else}
							<button
								onclick={() => expandedNoiseIndices = [...expandedNoiseIndices, i]}
								class="text-gray-700 hover:text-gray-500 text-xs italic"
							>... ({line.noiseCount} lines suppressed)</button>
						{/if}
					</div>
				{:else if isSeparator(line.raw)}
					<div class="py-2 text-center select-none opacity-60">
						<span class="text-gray-500 text-[10px]">{extractSeparatorText(line.raw)}</span><!-- separator -->
					</div>
				{:else if line.tag === 'CYCLE'}
					{@const style = getTagStyle(line.tag)}
					<div class="phase-separator {line.isStale ? 'opacity-30' : ''}">
						<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						<span class="font-mono text-[10px] text-muted-foreground">{line.message}</span>
					</div>
				{:else if line.tag === 'PHASE'}
					{@const style = getTagStyle(line.tag)}
					<div class="phase-separator {line.isStale ? 'opacity-30' : ''}">
						<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						<span class="font-mono text-[10px] text-muted-foreground">{line.message}</span>
					</div>
				{:else if line.tag === 'TOOL'}
					{@const style = getTagStyle(line.tag)}
					<div class="dr-log-line dr-log-line-tool flex items-start gap-2 py-0.5 leading-5 opacity-40">
						<span class="text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="shrink-0 w-[42px] text-right {style.text}">
							<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 truncate text-gray-500">
							{line.message}
						</span>
					</div>
				{:else if line.tag === 'RESULT'}
					{@const style = getTagStyle(line.tag)}
					{@const resultMatch = line.message.match(/^(\d+)→\s?(.*)/)}
					<div class="dr-log-line dr-log-line-result flex items-start gap-0 py-0 leading-5 opacity-60">
						{#if resultMatch}
							<span class="text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none text-right pr-1">{line.timestamp}</span>
							<span class="shrink-0 w-[42px] text-right {style.text}">
								<span class="dr-tag-badge {style.bg}">{line.tag}</span>
							</span>
							<span class="shrink-0 w-[36px] text-right pr-1 text-gray-600 tabular-nums select-none text-xs">{resultMatch[1]}</span>
							<span class="text-gray-600 select-none text-xs pr-1">→</span>
							<span class="flex-1 min-w-0 truncate text-gray-400 text-xs">{resultMatch[2]}</span>
						{:else}
							<span class="text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
							<span class="shrink-0 w-[42px] text-right {style.text}">
								<span class="dr-tag-badge {style.bg}">{line.tag}</span>
							</span>
							<span class="flex-1 min-w-0 truncate text-gray-400 text-xs">{line.message}</span>
						{/if}
					</div>
				{:else if line.tag}
					{@const style = getTagStyle(line.tag)}
					<div class="dr-log-line dr-log-line-{line.tag.toLowerCase()} flex items-start gap-2 py-0.5 leading-5 {line.tag === 'ERROR' ? 'bg-red-950/50 -mx-3 px-3 rounded' : ''}">
						<span class="text-xs text-gray-400/60 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="shrink-0 w-[42px] text-right {style.text}">
							<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 break-all {line.tag === 'ERROR' ? 'text-red-400' : line.tag === 'DONE' ? 'text-green-400' : 'text-gray-300'}">
							{line.message}
						</span>
					</div>
				{:else}
					<div class="py-0.5 leading-5 text-gray-400 break-all whitespace-pre-wrap max-h-[120px] overflow-y-auto">
						{line.raw}
					</div>
				{/if}
			{/each}
		{/if}
	</div>
</div>



