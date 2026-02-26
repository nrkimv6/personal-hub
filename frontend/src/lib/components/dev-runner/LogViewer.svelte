<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerLogApi } from '$lib/api';

	interface Props {
		planFile?: string;
		currentPlanName?: string;
		onBatchPlansChange?: (plans: BatchPlanItem[]) => void;
	}

	let { planFile, currentPlanName, onBatchPlansChange }: Props = $props();

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
	const MAX_LINES = 500;
	const SEPARATOR_PATTERN = '════════════════';

	const BASE_DELAY = 3000;

	// Tag colors for dark background
	const tagColors: Record<string, { text: string; bg: string }> = {
		AI: { text: 'text-blue-400', bg: 'bg-blue-500/20' },
		TOOL: { text: 'text-yellow-400', bg: 'bg-yellow-500/20' },
		DONE: { text: 'text-green-400', bg: 'bg-green-500/20' },
		RESULT: { text: 'text-emerald-400', bg: 'bg-emerald-500/20' },
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
		SKIP: { text: 'text-gray-500', bg: 'bg-gray-500/20' },
		GIT: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
		BATCH: { text: 'text-teal-400', bg: 'bg-teal-500/20' },
		NOISE: { text: 'text-gray-600', bg: 'bg-gray-700/20' }
	};

	const LINE_PATTERN = /^\s*\[?(\d{2}:\d{2}:\d{2})\]?\s*\[(\w+)\]\s*(.*)/;
	const DIAG_PATTERN = /^\[(\w+)\]\s*(.*)/;

	function parseLine(text: string, isStale: boolean): ParsedLine {
		const match = text.match(LINE_PATTERN);
		if (match) {
			return { timestamp: match[1], tag: match[2], message: match[3], raw: text, isStale };
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

		lines.push(parsed);
		if (lines.length > MAX_LINES) {
			lines = lines.slice(lines.length - MAX_LINES);
		}
		if (autoScroll && logContainer) {
			requestAnimationFrame(() => {
				logContainer.scrollTop = logContainer.scrollHeight;
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
					logContainer.scrollTop = logContainer.scrollHeight;
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

		// SSE 연결 전 status API로 실행 상태 + Redis 상태 확인
		await fetchStatus();

		eventSource = devRunnerLogApi.connectStream();
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
		eventSource.onerror = async () => {
			consecutiveErrors++;
			eventSource?.close();
			eventSource = null;

			connected = 'disconnected';
			reconnectCount++;
			await fetchStatus();
			setTimeout(connectSSE, getReconnectDelay());
		};
	}

	async function loadRecent() {
		try {
			const res = await devRunnerLogApi.recent(100);
			lines = res.lines.map((text: string) => parseLine(text, true));
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
			eventSource = null;
		}
	});

	function getTagStyle(tag: string) {
		return tagColors[tag] ?? tagColors.INFO;
	}

	// batchPlans 변경 시 부모에 알림
	$effect(() => {
		onBatchPlansChange?.(batchPlans);
	});

</script>

<div class="flex flex-col h-full min-h-0">
	<!-- Toolbar -->
	<div class="flex items-center justify-between px-3 py-2 border-b border-gray-700 shrink-0 bg-gray-900">
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
					class="h-6 px-2 text-[10px] text-gray-500 hover:bg-gray-700 rounded transition-colors inline-flex items-center gap-1"
					onclick={manualReconnect}
				>
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v6h6"/><path d="M3 13a9 9 0 1 0 3-7.7L3 8"/></svg>
					재연결
				</button>
			{/if}
			<button
				class="h-6 px-2 text-[10px] rounded transition-colors inline-flex items-center gap-1 {autoScroll ? 'text-blue-400' : 'text-gray-400'} hover:bg-gray-700"
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
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
					Pause
				{:else}
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
					Resume
					{#if pauseBuffer.length > 0}
						<span class="ml-0.5 text-[9px] bg-yellow-500/30 text-yellow-300 px-1 rounded-full leading-none py-0.5">
							{pauseBuffer.length}
						</span>
					{/if}
				{/if}
			</button>
		</div>
	</div>

	<!-- Log Content (Phase 2: text-sm for body) -->
	<div
		bind:this={logContainer}
		onscroll={handleScroll}
		class="flex-1 min-h-0 overflow-y-auto font-mono text-sm p-3 bg-gray-950 text-gray-300"
	>
		{#if lines.length === 0}
			<span class="text-gray-600">로그가 없습니다</span>
		{:else}
			{#each lines as line, i}
				{#if line.tag === 'NOISE'}
					<div class="py-0.5 leading-5 {line.isStale ? 'opacity-30' : ''}">
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
					<div class="py-2 text-center select-none {line.isStale ? 'opacity-25' : 'opacity-60'}">
						<span class="text-gray-500 text-[10px]">{extractSeparatorText(line.raw)}</span><!-- separator -->
					</div>
				{:else if line.tag === 'CYCLE'}
					<div class="py-1.5 -mx-3 px-3 mt-2 bg-gray-700/60 border-l-2 border-gray-400 {line.isStale ? 'opacity-30' : ''}">
						<span class="font-bold text-white text-xs tracking-wider">{line.message}</span>
					</div>
				{:else if line.tag === 'PHASE'}
					{@const style = getTagStyle(line.tag)}
					<div class="flex items-start gap-2 py-0.5 leading-5 mt-1.5 border-t border-indigo-900/40 {line.isStale ? 'opacity-30' : ''}">
						<span class="text-xs text-gray-400/60 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="text-xs shrink-0 w-[42px] text-right font-semibold {style.text}">
							<span class="rounded px-1 py-0.5 {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 break-all text-indigo-300 font-medium">
							{line.message}
						</span>
					</div>
				{:else if line.tag}
					{@const style = getTagStyle(line.tag)}
					<div class="flex items-start gap-2 py-0.5 leading-5 {line.isStale ? 'opacity-30' : ''} {line.tag === 'ERROR' ? 'bg-red-950/50 -mx-3 px-3 rounded' : ''}">
						<span class="text-xs text-gray-400/60 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="text-xs shrink-0 w-[42px] text-right font-semibold {style.text}">
							<span class="rounded px-1 py-0.5 {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 break-all {line.tag === 'ERROR' ? 'text-red-400' : line.tag === 'DONE' ? 'text-green-400' : 'text-gray-300'}">
							{line.message}
						</span>
					</div>
				{:else}
					<div class="py-0.5 leading-5 {line.isStale ? 'opacity-30' : ''} text-gray-400 break-all whitespace-pre-wrap max-h-[120px] overflow-y-auto">
						{line.raw}
					</div>
				{/if}
			{/each}
		{/if}
	</div>
</div>
