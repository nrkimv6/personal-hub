<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerLogApi } from '$lib/api';
	import { apiGate } from '$lib/stores/apiGate.svelte';
	import { createBackoff } from '$lib/dev-runner/backoff';
	import { BatchTracker } from '$lib/dev-runner/batch-tracker.svelte';
	import {
		defaultLineHandlers,
		type LinePipelineContext
	} from '$lib/dev-runner/line-pipeline';
	import { isStartOnlyRecentLog } from '$lib/dev-runner/log-recent-fallback.js';
	import { getLogLineVariant } from '$lib/dev-runner/log-line-variant';
	import {
		HEADER_ONLY_TAGS,
		SEPARATOR_PATTERN,
		buildSessionSeparator as buildParsedSessionSeparator,
		createLineId as createParsedLineId,
		extractLogIdentity,
		extractSeparatorText,
		isSeparator,
		parseLine as parseRawLine
	} from '$lib/dev-runner/log-parse';
	import {
		getExpandLabel,
		getPreviewLines,
		getRenderableText,
		isFailureResultBody,
		parseResultSegments,
		shouldCollapseMessage as shouldCollapseMessageBase
	} from '$lib/dev-runner/log-render';
	import { LogStream } from '$lib/dev-runner/log-stream.svelte';
	import { FILTERABLE_TAGS, getTagStyle } from '$lib/dev-runner/log-tags';
	import type { BatchPlanItem, ParsedLine } from '$lib/dev-runner/log-types';
	import { getExitReasonDisplay } from '$lib/utils/dev-runner-exit-reason';
	import { shouldShowMergeCompletionBanner } from '$lib/utils/dev-runner-merge-banner';
	import LogLine from './LogLine.svelte';
	import LogLineNoise from './LogLineNoise.svelte';
	import LogLineSeparator from './LogLineSeparator.svelte';

	interface Props {
		runnerId: string;
		planFile?: string;
		currentPlanName?: string;
		running?: boolean;
		mergeStatus?: string | null;
		mergeReason?: string | null;
		mergeMessage?: string | null;
		trigger?: string | null;
		mode?: 'standalone' | 'managed';
		engine?: string | null;
		worktreePath?: string | null;
		branch?: string | null;
		executionCount?: number | null;
		onBatchPlansChange?: (plans: BatchPlanItem[]) => void;
		onMergeCompleted?: (reason?: string, status?: string) => void;
	}

	let { runnerId, planFile, currentPlanName, running = false, mergeStatus = null, mergeReason = null, mergeMessage = null, trigger = null, mode = 'standalone', engine = null, worktreePath = null, branch = null, executionCount = null, onBatchPlansChange, onMergeCompleted }: Props = $props();
	let isCodexEngine = $derived((engine ?? '').toLowerCase() === 'codex');

	// 머지 진행 중 상태 판별
	let isMerging = $derived(
		['merge_pending', 'queued', 'merging', 'testing', 'fixing', 'resolving'].includes(mergeStatus ?? '')
	);

	const batchTracker = new BatchTracker();
	let batchPlans = $derived(batchTracker.plans);
	let batchDoneCount = $derived(batchTracker.doneCount);

	let lines = $state<ParsedLine[]>([]);
	let expandedNoiseIndices = $state<number[]>([]);
        let showNoiseIndicator = $state(false);
        let noiseTimer: ReturnType<typeof setTimeout> | null = null;
	let autoScroll = $state(true);
	let logContainer: HTMLDivElement;
	let pendingStale = $state(false);
	let exitBanner = $state<{ show: boolean; reason: string }>({ show: false, reason: 'completed' }); // runner 종료 배너
	let failureBanner = $state<{ show: boolean; message: string } | null>(null); // FAILURE 태그 sticky 배너
	let lastLogLoadError = $state<string | null>(null);
	let lastLogLoadStage = $state<string | null>(null);
	const MAX_LINES = 500;
	const PREVIEW_TOGGLE_STORAGE_KEY = 'devRunnerPreviewCollapse';
	const TAG_FILTER_STORAGE_KEY = 'devRunnerHiddenLogTags';
	let previewCollapsedEnabled = $state(true);
	let hiddenTags = $state<Set<string>>(new Set());
	let visibleLines = $derived(lines.filter((line) => !hiddenTags.has(line.tag)));
	let hiddenLogCount = $derived(lines.length - visibleLines.length);
	let lineSequence = 0;
	let loadedRecentLogIdentity = $state<string | null>(null);
	let fromLine = 0;
	let recentRetryTimer: ReturnType<typeof setTimeout> | null = null;
	const recentRetryBackoff = createBackoff({ baseMs: 600, maxMs: 60000, maxAttempts: 4 });

	let copyState = $state<'idle' | 'loading' | 'copied' | 'error'>('idle');
	let expandedLongLines = $state<Set<string>>(new Set());
	let runMetaExpanded = $state(false);

	const stream = new LogStream({
		runnerId: () => runnerId,
		mode: () => mode,
		running: () => running,
		isMerging: () => isMerging,
		getSinceLine: () => fromLine + lines.length,
		shouldLoadRecentBeforeReconnect: () => lines.length <= 3,
		loadRecent,
		addLine,
		clearNoiseTimer,
		hasExitBanner: () => exitBanner.show,
		clearExitBanner: () => {
			if (exitBanner.show) exitBanner = { show: false, reason: 'completed' };
		},
		showCompleted: (reason) => {
			exitBanner = { show: true, reason };
		}
	});
	let connected = $derived(stream.connected);
	let reconnectCount = $derived(stream.reconnectCount);
	let redisAvailable = $derived(stream.redisAvailable);

	let planBasename = $derived(
		planFile ? (planFile.split(/[\\/]/).pop() ?? planFile) : (currentPlanName ?? null)
	);
	let runMetaRows = $derived.by(() => [
		planBasename ? { label: 'Plan', value: planBasename } : null,
		{ label: 'Runner', value: runnerId },
		engine ? { label: 'Engine', value: engine } : null,
		branch ? { label: 'Branch', value: branch } : null,
		worktreePath ? { label: 'Worktree', value: worktreePath } : null,
		executionCount != null ? { label: 'Execution #', value: String(executionCount) } : null,
		trigger ? { label: 'Trigger', value: trigger } : null
	].filter((row): row is { label: string; value: string } => row !== null));
	let runMetaSummary = $derived.by(() => {
		const parts = [`runner ${runnerId}`];
		if (engine) parts.push(engine);
		if (trigger) parts.push(trigger);
		return `Run meta · ${parts.join(' · ')}`;
	});

	function createLineId(tag: string, timestamp: string, raw: string): string {
		lineSequence += 1;
		return createParsedLineId(lineSequence, tag, timestamp, raw);
	}

	function parseLine(text: string, isStale: boolean): ParsedLine {
		return parseRawLine(text, isStale, createLineId);
	}

	function shouldCollapseMessage(message: string): boolean {
		return shouldCollapseMessageBase(message, previewCollapsedEnabled);
	}

	function toggleExpand(lineId: string) {
		const next = new Set(expandedLongLines);
		if (next.has(lineId)) next.delete(lineId);
		else next.add(lineId);
		expandedLongLines = next;
	}

	function isExpanded(lineId: string): boolean {
		return expandedLongLines.has(lineId);
	}

	function isTagHidden(tag: string): boolean {
		return hiddenTags.has(tag);
	}

	function persistHiddenTags(next: Set<string>) {
		try {
			window.localStorage.setItem(TAG_FILTER_STORAGE_KEY, JSON.stringify([...next]));
		} catch {
			// localStorage unavailable in some environments
		}
	}

	function toggleTagHidden(tag: string) {
		const next = new Set(hiddenTags);
		if (next.has(tag)) next.delete(tag);
		else next.add(tag);
		hiddenTags = next;
		persistHiddenTags(next);
	}

	function handleExpandKeydown(event: KeyboardEvent, lineId: string) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			toggleExpand(lineId);
		}
	}

	function getExpandButtonClass(expanded: boolean): string {
		return expanded
			? 'shrink-0 text-[10px] ml-1 px-1 py-0.5 rounded border border-emerald-700/60 text-emerald-300 bg-emerald-950/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-400/70 active:scale-[0.98] whitespace-nowrap'
			: 'shrink-0 text-[10px] ml-1 px-1 py-0.5 rounded border border-gray-700/50 text-gray-500 hover:text-gray-300 hover:border-gray-500/70 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gray-400/70 active:scale-[0.98] whitespace-nowrap';
	}

	async function copyLog() {
		if (copyState === 'loading') return;
		copyState = 'loading';

		const headerLines: string[] = [];
		headerLines.push(`[Runner] ${runnerId}`);
		if (planFile) {
			const basename = planFile.split(/[\\/]/).pop() ?? planFile;
			headerLines.push(`[Plan] ${basename}`);
		}
		if (engine) headerLines.push(`[Engine] ${engine}`);
		if (branch) headerLines.push(`[Branch] ${branch}`);
		if (worktreePath) headerLines.push(`[Worktree] ${worktreePath}`);
		if (executionCount != null) headerLines.push(`[Execution] ${executionCount}`);
		if (trigger) headerLines.push(`[Trigger] ${trigger}`);
		if (mergeStatus) headerLines.push(`[MergeStatus] ${mergeStatus}`);
		if (mergeReason) headerLines.push(`[MergeReason] ${mergeReason}`);
		if (mergeMessage) headerLines.push(`[MergeMessage] ${mergeMessage}`);
		headerLines.push('---');

		let logLines: string[];
		let usedFallback = false;
		try {
			// full log API로 원천 취득 (isStale/truncation 없이 raw 그대로)
			const res = await devRunnerLogApi.full(runnerId, 0, 5000);
			logLines = res.lines.filter((raw: string) => {
				const parsed = parseRawLine(raw, true, createLineId);
				return parsed.tag !== 'NOISE';
			});
		} catch {
			// full fetch 실패 시 현재 lines fallback (부분 복사 가능성 명시)
			usedFallback = true;
			logLines = lines
				.filter(l => l.tag !== 'NOISE')
				.map(l => l.raw);
		}

		if (usedFallback) {
			headerLines.push('[Fallback] full log fetch failed — partial copy');
		}

		const text = [...headerLines, ...logLines].join('\n');
		try {
			await navigator.clipboard.writeText(text);
			copyState = 'copied';
			setTimeout(() => { copyState = 'idle'; }, 1500);
		} catch {
			copyState = 'error';
			setTimeout(() => { copyState = 'idle'; }, 1500);
		}
	}

	function addLine(text: string, isStale: boolean) {
		const parsed = parseLine(text, isStale);
		const context: LinePipelineContext = {
			isStale,
			hasSeparator: isSeparator,
			markExistingLinesStale: () => {
				lines = lines.map((l) => ({ ...l, isStale: true }));
			},
			getPendingStale: () => pendingStale,
			setPendingStale: (value) => {
				pendingStale = value;
			},
			showNoiseIndicator: () => {
				showNoiseIndicator = true;
				if (noiseTimer) clearTimeout(noiseTimer);
				noiseTimer = setTimeout(() => {
					showNoiseIndicator = false;
					noiseTimer = null;
				}, 2000);
			},
			hideNoiseIndicator: () => {
				showNoiseIndicator = false;
				if (noiseTimer) {
					clearTimeout(noiseTimer);
					noiseTimer = null;
				}
			},
			batchTracker,
			showFailureBanner: (message) => {
				failureBanner = { show: true, message };
			}
		};
		for (const handler of defaultLineHandlers) handler(parsed, context);
		pushLine(parsed);
	}

	function describeError(error: unknown): string {
		if (error instanceof Error && error.message) return error.message;
		if (typeof error === 'string' && error) return error;
		return 'unknown error';
	}

	function clearRecentRetryTimer() {
		if (!recentRetryTimer) return;
		clearTimeout(recentRetryTimer);
		recentRetryTimer = null;
	}

	function clearNoiseTimer() {
		if (!noiseTimer) return;
		clearTimeout(noiseTimer);
		noiseTimer = null;
	}

	function hasLoadedLogContent(): boolean {
		return lines.some((line) => !HEADER_ONLY_TAGS.has(line.tag));
	}

	let emptyLogMessage = $derived.by(() => {
		if (lastLogLoadError) return `로그 로드 상태: ${lastLogLoadError}`;
		if (mode === 'managed' && recentRetryBackoff.attempts > 0) return '로그 catch-up 재시도 중입니다';
		if (mode === 'managed' && (running || apiGate.state === 'open')) return '로그 파일을 찾는 중입니다';
		return '표시할 로그가 아직 없습니다';
	});

	function recordLogLoadError(stage: string, error: unknown) {
		const message = describeError(error);
		lastLogLoadStage = stage;
		lastLogLoadError = `${stage}: ${message}`;
		addLine(`[DIAG] ${stage} 실패: ${message}`, false);
	}

	function recordLogDiagnostic(stage: string, diagnostic: string | null | undefined, source?: string | null) {
		if (!diagnostic) return;
		lastLogLoadStage = stage;
		lastLogLoadError = `${stage}: ${diagnostic}${source ? ` (${source})` : ''}`;
		addLine(`[DIAG] ${lastLogLoadError}`, false);
	}

	function scheduleManagedRecentRetry(reason: string) {
		if (mode !== 'managed' || hasLoadedLogContent() || recentRetryTimer) return;
		const delay = recentRetryBackoff.nextDelay();
		if (delay === null) {
			const stage = lastLogLoadStage ?? 'recent';
			addLine(`[DIAG] log source not found runner_id=${runnerId} stage=${stage} reason=${lastLogLoadError ?? reason}`, false);
			return;
		}
		recentRetryTimer = setTimeout(async () => {
			recentRetryTimer = null;
			if (mode !== 'managed' || hasLoadedLogContent()) return;
			addLine(`[DIAG] 로그 catch-up 재시도 #${recentRetryBackoff.attempts}: ${reason}`, false);
			await loadRecent();
			if (!hasLoadedLogContent() && (running || apiGate.state === 'open')) {
				scheduleManagedRecentRetry(reason);
			}
		}, delay);
	}

	function pushLine(parsed: ParsedLine) {
		lines.push(parsed);
		if (lines.length > MAX_LINES) {
			lines = lines.slice(lines.length - MAX_LINES);
			const validIds = new Set(lines.map((line) => line.id));
			const nextExpanded = new Set<string>();
			for (const id of expandedLongLines) {
				if (validIds.has(id)) nextExpanded.add(id);
			}
			expandedLongLines = nextExpanded;
		}
		if (autoScroll && logContainer) {
			requestAnimationFrame(() => {
				if (logContainer) logContainer.scrollTop = logContainer.scrollHeight;
			});
		}
	}

	function resumeLog() {
		autoScroll = true;
		scrollToBottom();
	}

	function scrollToBottom() {
		if (logContainer) {
			logContainer.scrollTop = logContainer.scrollHeight;
			autoScroll = true;
		}
	}

	function handleScroll() {
		if (!logContainer) return;
		const { scrollTop, clientHeight, scrollHeight } = logContainer;
		const atBottom = scrollHeight - scrollTop - clientHeight < 30;
		if (atBottom && !autoScroll) {
			autoScroll = true;
		}
	}

	function manualReconnect() {
		void stream.reconnect();
	}

	async function loadFull(): Promise<boolean> {
		try {
			const res = await devRunnerLogApi.full(runnerId, 0, 500);
			if (res.lines.length > 0) {
				lines = res.lines.map((text: string) => parseLine(text, true));
				expandedLongLines = new Set();
				lastLogLoadError = null;
				lastLogLoadStage = null;
				recentRetryBackoff.reset();
				clearRecentRetryTimer();
				return true;
			}
			recordLogDiagnostic('full', res.diagnostic, res.source);
		} catch (error) {
			recordLogLoadError('full 로그 로드', error);
		}
		return false;
	}

	function buildSessionSeparator(identity: string): ParsedLine {
		return buildParsedSessionSeparator(identity, createLineId);
	}

	async function loadRecent() {
		try {
			const res = await devRunnerLogApi.recent(runnerId, 500);
			fromLine = res.from_line ?? 0;
			let sourceLines = res.lines;
			if (!running && (sourceLines.length === 0 || isStartOnlyRecentLog(sourceLines))) {
				try {
					const fullRes = await devRunnerLogApi.full(runnerId, 0, 500);
					if (fullRes.lines.length > 0) {
						sourceLines = fullRes.lines;
						fromLine = fullRes.offset ?? 0;
					} else {
						recordLogDiagnostic('full', fullRes.diagnostic, fullRes.source);
					}
				} catch (error) {
					recordLogLoadError('recent fallback full 로그 로드', error);
				}
			}
			const parsed = sourceLines.map((text: string) => parseLine(text, true));
			const parsedHasContent = parsed.some((line: ParsedLine) => !HEADER_ONLY_TAGS.has(line.tag));
			if (!parsedHasContent && hasLoadedLogContent()) {
				recordLogDiagnostic('recent', res.diagnostic, res.source);
				return;
			}

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

			const nextIdentity = extractLogIdentity(parsed);
			const shouldAppendSession =
				lines.length > 0 &&
				nextIdentity !== null &&
				loadedRecentLogIdentity !== null &&
				nextIdentity !== loadedRecentLogIdentity;

			if (shouldAppendSession) {
				const staleExisting = lines.map((line) => ({ ...line, isStale: true }));
				const currentParsed = parsed.map((line) => ({ ...line, isStale: false }));
				lines = [...staleExisting, buildSessionSeparator(nextIdentity), ...currentParsed].slice(-MAX_LINES);
			} else {
				lines = parsed;
			}
			if (nextIdentity !== null) {
				loadedRecentLogIdentity = nextIdentity;
			}
			expandedLongLines = new Set();

			// running 중 500줄 꽉 찼으면 더 오래된 로그가 있음 → loadFull로 전체 재로드
			if (running && parsed.length === 500) {
				await loadFull();
			}

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
			lastLogLoadError = null;
			lastLogLoadStage = null;
			if (hasLoadedLogContent()) {
				recentRetryBackoff.reset();
				clearRecentRetryTimer();
			}
		} catch (error) {
			recordLogLoadError('recent 로그 로드', error);
			scheduleManagedRecentRetry('recent 로그 로드 실패');
		}
	}

	async function runDiagnostics() {
		try {
			const diag = await devRunnerLogApi.diagnostics();
			for (const s of diag.steps) {
				const icon = s.ok ? 'OK' : 'NG';
				addLine(`[DIAG] ${s.step}. ${s.name} ... ${icon} ${s.detail}`, false);
			}
		} catch {
			addLine('[DIAG] 진단 API 호출 실패 (API 서버 미응답)', false);
		}
	}

	onMount(async () => {
		try {
			const stored = window.localStorage.getItem(PREVIEW_TOGGLE_STORAGE_KEY);
			if (stored === 'off') {
				previewCollapsedEnabled = false;
			}
			const storedTags = window.localStorage.getItem(TAG_FILTER_STORAGE_KEY);
			if (storedTags) {
				const parsedTags = JSON.parse(storedTags);
				if (Array.isArray(parsedTags)) {
					hiddenTags = new Set(parsedTags.filter((tag): tag is string => FILTERABLE_TAGS.includes(tag)));
				}
			}
		} catch {
			// localStorage unavailable in some environments
		}
		void runDiagnostics();
		await loadRecent();
		// 초기 로드 후 스크롤을 맨 아래로 이동
		requestAnimationFrame(() => scrollToBottom());
		await stream.start();
		if (mode === 'managed') {
			if (!hasLoadedLogContent()) scheduleManagedRecentRetry('managed mount');
		}
	});

	onDestroy(() => {
		stream.stop();
		clearRecentRetryTimer();
	});

	// 탭 전환 시 (hidden→visible) autoScroll=true이면 맨 아래로 복원
	$effect(() => {
		if (!logContainer) return;
		const observer = new MutationObserver(() => {
			if (logContainer.offsetParent !== null && autoScroll) {
				logContainer.scrollTop = logContainer.scrollHeight;
			}
		});
		// 부모 요소의 class(hidden) 변경 감지
		const parent = logContainer.parentElement;
		if (parent) {
			observer.observe(parent, { attributes: true, attributeFilter: ['class'] });
		}
		return () => observer.disconnect();
	});

	// batchPlans 변경 시 부모에 알림
	$effect(() => {
		onBatchPlansChange?.(batchPlans);
	});

	// mergeStatus 전환 시 SSE 재연결 (standalone 모드에서만, runner → merge stream 또는 반대)
	let prevMerging: boolean | undefined;
	$effect(() => {
		const cur = isMerging;
		if (mode === 'standalone' && prevMerging !== undefined && prevMerging !== cur) {
			void stream.reconnectForModeSwitch(
				cur ? '[MERGE] 머지 로그 스트림으로 전환...' : '[MERGE] 러너 로그 스트림으로 복귀...'
			);
		}
		prevMerging = cur;
	});

	let previousManagedRetryKey = '';
	$effect(() => {
		const retryKey = `${runnerId}|${running ? 'running' : 'stopped'}|${apiGate.state}`;
		if (mode !== 'managed') {
			previousManagedRetryKey = retryKey;
			return;
		}
		if (previousManagedRetryKey === retryKey) return;
		previousManagedRetryKey = retryKey;
		recentRetryBackoff.reset();
		if (!hasLoadedLogContent()) {
			scheduleManagedRecentRetry('runner/api state changed');
		}
	});

	// ── managed 모드 공개 API ───────────────────────────────────────────────────

	let _catchUpInProgress = false;
	let _catchUpPromise: Promise<void> | null = null;
	let _pendingInjectBuffer: string[] = [];

	export function injectLine(payload: string | { text: string; meta?: Record<string, unknown> }) {
		const text = typeof payload === 'string' ? payload : payload?.text;
		if (typeof text !== 'string') return;
		if (_catchUpInProgress) {
			_pendingInjectBuffer.push(text);
			return;
		}
		addLine(text, false);
	}

	export async function catchUp(): Promise<void> {
		if (mode !== 'managed') return;
		if (_catchUpPromise) return _catchUpPromise;
		_catchUpPromise = (async () => {
			_catchUpInProgress = true;
			try {
				await loadRecent();
				// loadRecent 후 파일의 마지막 라인 이후에 도착한 펜딩 라인만 flush
				if (_pendingInjectBuffer.length > 0) {
					const lastFileLine = lines.length > 0 ? lines[lines.length - 1].raw : null;
					let startIdx = 0;
					if (lastFileLine) {
						const matchIdx = _pendingInjectBuffer.lastIndexOf(lastFileLine);
						if (matchIdx >= 0) startIdx = matchIdx + 1;
					}
					for (let i = startIdx; i < _pendingInjectBuffer.length; i++) {
						addLine(_pendingInjectBuffer[i], false);
					}
				}
				if (!hasLoadedLogContent()) scheduleManagedRecentRetry('managed catch-up');
			} finally {
				_pendingInjectBuffer = [];
				_catchUpInProgress = false;
				_catchUpPromise = null;
				requestAnimationFrame(() => scrollToBottom());
			}
		})();
		return _catchUpPromise;
	}

	export function injectCompleted(reason: string = 'completed') {
		stream.complete(reason);
	}

	export function injectMergeCompleted(reason?: string, status?: string) {
		// running 상태에서는 배너 표시 건너뜀 — 잘못된 FAILED sentinel이 흘러와도 깜빡임 방지
		if (running) {
			onMergeCompleted?.(reason, status);
			return;
		}
		onMergeCompleted?.(reason, status);
		if (shouldShowMergeCompletionBanner(reason, status)) {
			injectCompleted(reason ?? 'merge_failed');
		}
	}

</script>

<div class="flex flex-col h-full min-h-0">
	<!-- Toolbar -->
	<div class="flex items-center justify-between px-3 py-2 border-b border-border shrink-0 bg-gray-900">
		<div class="flex items-center gap-2">
			<span class="hidden text-xs font-medium uppercase tracking-wider text-gray-300 sm:inline">Live Logs</span>
			<!-- trigger 배지 -->
			{#if trigger}
				{@const t = trigger}
				<span class="text-[9px] px-1.5 py-0.5 rounded font-mono {t === 'user' ? 'bg-blue-500/20 text-blue-300' : t === 'user:all' ? 'bg-green-500/20 text-green-300' : t.startsWith('tc:') ? 'bg-orange-500/20 text-orange-300' : 'bg-gray-500/20 text-gray-400'}">
					{t}
				</span>
			{/if}
			{#if isCodexEngine}
				<span class="text-[9px] px-1.5 py-0.5 rounded font-mono bg-slate-500/20 text-slate-300">
					realtime
				</span>
			{/if}
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
			<div class="hidden items-center gap-1 sm:flex">
				{#each FILTERABLE_TAGS as tag}
					<button
						type="button"
						class="rounded border px-1.5 py-0.5 text-[9px] font-mono transition-colors {isTagHidden(tag) ? 'border-gray-700 bg-gray-800 text-gray-500' : 'border-red-500/40 bg-red-500/10 text-red-300'}"
						title={isTagHidden(tag) ? `${tag} 로그 보이기` : `${tag} 로그 숨기기`}
						aria-pressed={!isTagHidden(tag)}
						onclick={() => toggleTagHidden(tag)}
					>
						{tag}
					</button>
				{/each}
				{#if hiddenLogCount > 0}
					<span class="rounded bg-gray-800 px-1.5 py-0.5 text-[9px] font-mono text-gray-400" title="필터로 숨겨진 로그 수">
						hidden {hiddenLogCount}
					</span>
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
			<!-- 로그 복사 버튼 -->
			<button
				class="h-6 w-6 rounded transition-colors inline-flex items-center justify-center {copyState === 'copied' ? 'text-green-400' : copyState === 'error' ? 'text-red-400' : copyState === 'loading' ? 'text-yellow-400' : 'text-gray-400'} hover:bg-gray-700 disabled:cursor-not-allowed"
				title={copyState === 'copied' ? '복사됨' : copyState === 'error' ? '복사 실패' : copyState === 'loading' ? '복사 중...' : '로그 복사 (full log + 머지 상태)'}
				onclick={copyLog}
				disabled={copyState === 'loading'}
			>
				{#if copyState === 'copied'}
					<!-- Check icon -->
					<svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
				{:else if copyState === 'error'}
					<!-- X icon -->
					<svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
				{:else if copyState === 'loading'}
					<!-- Spinner icon -->
					<svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
				{:else}
					<!-- Clipboard icon -->
					<svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></svg>
				{/if}
			</button>
			<button
				class="relative h-6 w-6 rounded transition-colors inline-flex items-center justify-center {autoScroll ? 'text-primary' : 'text-muted-foreground'} hover:bg-gray-700"
				title={autoScroll ? 'Pin (auto-scroll on)' : 'Unpin (auto-scroll off)'}
				onclick={() => {
					if (autoScroll) {
						autoScroll = false;
					} else {
						autoScroll = true;
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
				{/if}
			</button>
		</div>
	</div>

	<div class="shrink-0 border-b border-gray-800 bg-gray-950/80 px-3 py-1 text-[10px] text-gray-400">
		<button
			type="button"
			class="flex w-full min-w-0 items-center gap-1 text-left font-mono text-gray-400 hover:text-gray-200 focus:outline-none focus:ring-1 focus:ring-gray-600"
			aria-expanded={runMetaExpanded}
			onclick={() => runMetaExpanded = !runMetaExpanded}
			title="runner, plan, branch, worktree 메타 정보"
		>
			<span class="shrink-0">{runMetaExpanded ? '▾' : '▸'}</span>
			<span class="min-w-0 truncate">{runMetaSummary}</span>
		</button>
		{#if runMetaExpanded}
			<div class="mt-1 grid gap-x-3 gap-y-1 sm:grid-cols-2">
				{#each runMetaRows as row}
					<div class="flex min-w-0 gap-1.5">
						<span class="shrink-0 text-gray-500">{row.label}</span>
						<span class="min-w-0 truncate text-gray-300" title={row.value}>{row.value}</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	{#if !redisAvailable && connected === 'connected'}
		<div class="px-3 py-1.5 bg-red-900/40 border-b border-red-700/50 text-xs text-red-300 shrink-0 flex items-center gap-2">
			<span>Redis 연결 불가 — 관리자 도구에서 redis-restart 실행</span>
		</div>
	{/if}

	{#if exitBanner.show}
		{@const exitDisplay = getExitReasonDisplay(exitBanner.reason)}
		<div class={exitDisplay.bannerClass}>
			<span>{exitDisplay.bannerText}</span>
		</div>
	{/if}

	{#if failureBanner?.show}
		<div class="sticky top-0 z-10 flex items-center justify-between gap-2 px-3 py-1.5 bg-red-900/80 border-l-4 border-red-500 text-red-200 text-xs font-mono">
			<span class="font-bold text-red-300">[FAILURE]</span>
			<span class="flex-1 min-w-0 truncate">{failureBanner.message}</span>
			<button
				type="button"
				onclick={() => { if (failureBanner) failureBanner = { ...failureBanner, show: false }; }}
				class="shrink-0 text-red-400 hover:text-red-200 leading-none"
				aria-label="배너 닫기"
			>✕</button>
		</div>
	{/if}

	{#if lastLogLoadError}
		<div class="px-3 py-1.5 bg-yellow-950/50 border-b border-yellow-800/60 text-[11px] text-yellow-200 shrink-0 font-mono">
			[DIAG] {lastLogLoadError}
		</div>
	{/if}

	<!-- Log Content (Phase 2: text-sm for body) -->
	<div
		bind:this={logContainer}
		onscroll={handleScroll}
		class="flex-1 min-h-0 overflow-y-auto font-mono text-xs p-1.5 bg-gray-950 text-gray-300 dr-scrollbar-thin"
	>
		{#if lines.length === 0}
			<span class="text-gray-600">{emptyLogMessage}</span>
		{:else if visibleLines.length === 0}
			<span class="text-gray-600">{hiddenLogCount}개 로그가 필터로 숨겨졌습니다</span>
		{:else}
			{#each visibleLines as line, i}
				{#if line.tag === 'NOISE'}
					<LogLineNoise
						{line}
						expanded={expandedNoiseIndices.includes(i)}
						onExpand={() => expandedNoiseIndices = [...expandedNoiseIndices, i]}
						onCollapse={() => expandedNoiseIndices = expandedNoiseIndices.filter(n => n !== i)}
					/>
				{:else if isSeparator(line.raw)}
					<LogLineSeparator text={extractSeparatorText(line.raw)} />
				{:else if line.tag === 'CYCLE'}
					{@const style = getTagStyle(line.tag)}
					{@const cycleInfo = getLogLineVariant(line)}
					{@const cycleExpanded = isExpanded(line.id)}
					{@const cycleCollapsed = shouldCollapseMessage(line.message)}
					<LogLine
						{line}
						{style}
						variant={cycleInfo.variant}
						containerClass={cycleInfo.containerClass}
						bodyClass={cycleInfo.bodyClass}
						expanded={cycleExpanded}
						collapsed={cycleCollapsed}
						expandLabel={getExpandLabel(line.message)}
						expandButtonClass={getExpandButtonClass(cycleExpanded)}
						onToggleExpand={() => toggleExpand(line.id)}
						onExpandKeydown={(e) => handleExpandKeydown(e, line.id)}
					>
						{cycleCollapsed && !cycleExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
					</LogLine>
				{:else if line.tag === 'PHASE'}
					{@const style = getTagStyle(line.tag)}
					{@const phaseInfo = getLogLineVariant(line)}
					{@const phaseExpanded = isExpanded(line.id)}
					{@const phaseCollapsed = shouldCollapseMessage(line.message)}
					<LogLine
						{line}
						{style}
						variant={phaseInfo.variant}
						containerClass={phaseInfo.containerClass}
						bodyClass={phaseInfo.bodyClass}
						expanded={phaseExpanded}
						collapsed={phaseCollapsed}
						expandLabel={getExpandLabel(line.message)}
						expandButtonClass={getExpandButtonClass(phaseExpanded)}
						onToggleExpand={() => toggleExpand(line.id)}
						onExpandKeydown={(e) => handleExpandKeydown(e, line.id)}
					>
						{phaseCollapsed && !phaseExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
					</LogLine>
				{:else if line.tag === 'TOOL'}
					{@const style = getTagStyle(line.tag)}
					{@const toolInfo = getLogLineVariant(line)}
					{@const toolExpanded = isExpanded(line.id)}
					{@const toolCollapsed = shouldCollapseMessage(line.message)}
					<LogLine
						{line}
						{style}
						variant={toolInfo.variant}
						containerClass={toolInfo.containerClass}
						bodyClass={toolInfo.bodyClass}
						timestampClass={toolInfo.timestampClass}
						expanded={toolExpanded}
						collapsed={toolCollapsed}
						expandLabel={getExpandLabel(line.message)}
						expandButtonClass={getExpandButtonClass(toolExpanded)}
						onToggleExpand={() => toggleExpand(line.id)}
						onExpandKeydown={(e) => handleExpandKeydown(e, line.id)}
					>
						{#if line.structured?.name}
							<span class="mr-1 shrink-0 rounded bg-yellow-500/10 px-1 text-[10px] font-semibold text-yellow-200">{line.structured.name}</span>
						{/if}
						{toolCollapsed && !toolExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
					</LogLine>
				{:else if line.tag === 'RESULT'}
					{@const style = getTagStyle(line.tag)}
					{@const resultSegments = parseResultSegments(line.message)}
					{@const resultMatch = resultSegments.length === 1 ? resultSegments[0] : null}
					{@const resultBody = resultMatch ? resultMatch.text : line.message}
					{@const resultExpanded = isExpanded(line.id)}
					{@const resultCollapsed = shouldCollapseMessage(resultBody)}
					{@const resultIsFailure = isFailureResultBody(resultBody)}
					{@const resultInfo = getLogLineVariant(line, { resultFailure: resultIsFailure })}
					<LogLine
						{line}
						{style}
						variant={resultInfo.variant}
						containerClass={resultInfo.containerClass}
						bodyClass={resultInfo.bodyClass}
						timestampClass={resultInfo.timestampClass}
						badgeWrapperClass={resultInfo.badgeWrapperClass}
						expanded={resultExpanded}
						collapsed={resultCollapsed}
						expandLabel={getExpandLabel(resultBody)}
						expandButtonClass={getExpandButtonClass(resultExpanded)}
						onToggleExpand={() => toggleExpand(line.id)}
						onExpandKeydown={(e) => handleExpandKeydown(e, line.id)}
					>
						{#if resultMatch}
							<span class="flex-1 min-w-0 flex items-baseline bg-gray-900/60 rounded px-1 font-mono">
								<span class="shrink-0 w-[28px] text-right pr-1.5 text-gray-600 tabular-nums select-none text-[10px]">{resultMatch.num}</span>
								<span class="text-gray-500 select-none text-[10px] pr-1">→</span>
								{#if resultIsFailure}
									<span class="shrink-0 mr-1 rounded bg-red-500/20 px-1 text-[10px] font-semibold text-red-200">FAIL</span>
								{/if}
								<span class="flex-1 min-w-0 break-all whitespace-pre-wrap {resultIsFailure ? 'text-red-200' : 'text-emerald-300/80'} text-[11px]">
									{resultCollapsed && !resultExpanded ? getPreviewLines(resultBody) : getRenderableText(resultBody)}
								</span>
							</span>
						{:else}
							{#if resultIsFailure}
								<span class="shrink-0 mx-1 rounded bg-red-500/20 px-1 text-[10px] font-semibold text-red-200">FAIL</span>
							{/if}
							<span class="flex-1 min-w-0 break-all whitespace-pre-wrap {resultIsFailure ? 'text-red-200' : 'text-gray-400'} text-xs">
								{resultCollapsed && !resultExpanded ? getPreviewLines(resultBody) : getRenderableText(resultBody)}
							</span>
						{/if}
					</LogLine>
				{:else if line.tag}
					{@const style = getTagStyle(line.tag)}
					{@const lineInfo = getLogLineVariant(line)}
					{@const lineExpanded = isExpanded(line.id)}
					{@const lineCollapsed = shouldCollapseMessage(line.message)}
					<LogLine
						{line}
						{style}
						variant={lineInfo.variant}
						containerClass={lineInfo.containerClass}
						bodyClass={lineInfo.bodyClass}
						title={lineInfo.title}
						expanded={lineExpanded}
						collapsed={lineCollapsed}
						expandLabel={getExpandLabel(line.message)}
						expandButtonClass={getExpandButtonClass(lineExpanded)}
						onToggleExpand={() => toggleExpand(line.id)}
						onExpandKeydown={(e) => handleExpandKeydown(e, line.id)}
					>
						{lineCollapsed && !lineExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
					</LogLine>
				{:else}
					{@const rawExpanded = isExpanded(line.id)}
					{@const rawCollapsed = shouldCollapseMessage(line.raw)}
					<div class="py-0.5 leading-5 text-gray-400 break-all whitespace-pre-wrap flex items-start">
						<span class="flex-1 min-w-0">
							{rawCollapsed && !rawExpanded ? getPreviewLines(line.raw) : getRenderableText(line.raw)}
						</span>
						{#if rawCollapsed}
							<button
								type="button"
								class={getExpandButtonClass(rawExpanded)}
								aria-expanded={rawExpanded}
								aria-pressed={rawExpanded}
								onclick={() => toggleExpand(line.id)}
								onkeydown={(e) => handleExpandKeydown(e, line.id)}
							>
								{rawExpanded ? '접기' : getExpandLabel(line.raw)}
							</button>
						{/if}
					</div>
				{/if}
			{/each}
		{/if}
	</div>
</div>



