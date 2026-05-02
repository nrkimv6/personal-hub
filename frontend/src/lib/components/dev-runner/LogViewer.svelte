<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerLogApi } from '$lib/api';
	import { apiGate } from '$lib/stores/apiGate.svelte';
	import { getExitReasonDisplay } from '$lib/utils/dev-runner-exit-reason';
	import { shouldShowMergeCompletionBanner } from '$lib/utils/dev-runner-merge-banner';

	interface Props {
		runnerId: string;
		planFile?: string;
		currentPlanName?: string;
		running?: boolean;
		mergeStatus?: string | null;
		trigger?: string | null;
		mode?: 'standalone' | 'managed';
		engine?: string | null;
		worktreePath?: string | null;
		branch?: string | null;
		onBatchPlansChange?: (plans: BatchPlanItem[]) => void;
		onMergeCompleted?: (reason?: string, status?: string) => void;
	}

	let { runnerId, planFile, currentPlanName, running = false, mergeStatus = null, trigger = null, mode = 'standalone', engine = null, worktreePath = null, branch = null, onBatchPlansChange, onMergeCompleted }: Props = $props();
	let isCodexEngine = $derived((engine ?? '').toLowerCase() === 'codex');

	// 머지 진행 중 상태 판별
	let isMerging = $derived(
		['merge_pending', 'queued', 'merging', 'testing', 'fixing', 'resolving'].includes(mergeStatus ?? '')
	);

	// Phase 2: 전체실행 시 Plan 파일 리스트 추적
	interface BatchPlanItem {
		name: string;
		status: 'pending' | 'running' | 'done';
	}
	let batchPlans = $state<BatchPlanItem[]>([]);
	let batchDoneCount = $derived(batchPlans.filter(p => p.status === 'done').length);

	interface ParsedLine {
		id: string;
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
	let connected = $state<'connected' | 'disconnected'>(mode === 'managed' ? 'connected' : 'disconnected');
	let autoScroll = $state(true);
	let logContainer: HTMLDivElement;
	let eventSource: EventSource | null = null;
	let sseStarted = $state(mode === 'managed');
	let reconnectCount = $state(0);
	let consecutiveErrors = $state(0);
	let redisAvailable = $state(false);
	let pendingStale = $state(false);
	let exitBanner = $state<{ show: boolean; reason: string }>({ show: false, reason: 'completed' }); // runner 종료 배너
	let failureBanner = $state<{ show: boolean; message: string } | null>(null); // FAILURE 태그 sticky 배너
	const MAX_LINES = 500;
	const SEPARATOR_PATTERN = '════════════════';
	const PREVIEW_LINE_LIMIT = 3;
	const MAX_RENDER_CHARS = 8 * 1024;
	const PREVIEW_TOGGLE_STORAGE_KEY = 'devRunnerPreviewCollapse';
	let previewCollapsedEnabled = $state(true);
	let lineSequence = 0;

	let copied = $state(false);
	let expandedLongLines = $state<Set<string>>(new Set());

	const BASE_DELAY = 3000;

	// Tag colors for dark background
	const tagColors: Record<string, { text: string; bg: string }> = {
		AI: { text: 'text-blue-400', bg: 'bg-blue-500/20' },
		TOOL: { text: 'text-yellow-700', bg: 'bg-yellow-900/20' },
		DONE: { text: 'text-green-400', bg: 'bg-green-500/20' },
		RESULT: { text: 'text-emerald-700', bg: 'bg-emerald-900/20' },
		ERROR: { text: 'text-red-400', bg: 'bg-red-500/20' },
		FAILURE: { text: 'text-red-300', bg: 'bg-red-600/38' },
		HOLD: { text: 'text-yellow-300', bg: 'bg-yellow-600/20' },
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
	const PR_PREFIX_PATTERN = /^\[PR:[^\]]+\]\s*/;

	function normalizeLogText(text: string): string {
		return text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
	}

	function createLineId(tag: string, timestamp: string, raw: string): string {
		lineSequence += 1;
		const seed = `${tag}|${timestamp}|${raw}`;
		let hash = 0;
		for (let i = 0; i < seed.length; i++) {
			hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
		}
		return `${lineSequence}-${Math.abs(hash)}`;
	}

	function parseLine(text: string, isStale: boolean): ParsedLine {
		const normalizedRaw = normalizeLogText(text);
		const [head = '', ...tail] = normalizedRaw.split('\n');
		const tailText = tail.length > 0 ? `\n${tail.join('\n')}` : '';

		// [PR:name#hash|PID:12345] prefix 제거 후 일반 파싱
		const strippedHead = head.replace(PR_PREFIX_PATTERN, '');
		const finalMatch = strippedHead.match(LINE_PATTERN);
		if (finalMatch) {
			const message = `${finalMatch[3]}${tailText}`;
			return {
				id: createLineId(finalMatch[2], finalMatch[1], normalizedRaw),
				timestamp: finalMatch[1],
				tag: finalMatch[2],
				message,
				raw: normalizedRaw,
				isStale
			};
		}
		// [MERGE][TAG] message 형식 (머지 로그)
		const mergeMatch = strippedHead.match(MERGE_TAG_PATTERN);
		if (mergeMatch) {
			const message = `${mergeMatch[2]}${tailText}`;
			return {
				id: createLineId(mergeMatch[1], '', normalizedRaw),
				timestamp: '',
				tag: mergeMatch[1],
				message,
				raw: normalizedRaw,
				isStale
			};
		}
		const diagMatch = strippedHead.match(DIAG_PATTERN);
		if (diagMatch) {
			const tag = diagMatch[1];
			const message = `${diagMatch[2]}${tailText}`;
			if (tag === 'NOISE') {
				const noiseCount = parseInt(diagMatch[2]) || 0;
				return { id: createLineId(tag, '', normalizedRaw), timestamp: '', tag, message, raw: normalizedRaw, isStale, noiseCount };
			}
			return { id: createLineId(tag, '', normalizedRaw), timestamp: '', tag, message, raw: normalizedRaw, isStale };
		}
		return {
			id: createLineId('', '', normalizedRaw),
			timestamp: '',
			tag: '',
			message: normalizedRaw,
			raw: normalizedRaw,
			isStale
		};
	}

	function isSeparator(text: string): boolean {
		return text.includes(SEPARATOR_PATTERN);
	}

	function extractSeparatorText(text: string): string {
		return text.replace(/[═=\s]+/g, ' ').trim() || '새 세션';
	}

	function getRenderableText(message: string): string {
		const normalized = normalizeLogText(message);
		if (normalized.length <= MAX_RENDER_CHARS) return normalized;
		const hiddenChars = normalized.length - MAX_RENDER_CHARS;
		return `${normalized.slice(0, MAX_RENDER_CHARS)}\n… ${hiddenChars} chars truncated`;
	}

	function getPreviewLines(message: string, maxLines: number = PREVIEW_LINE_LIMIT): string {
		const renderable = getRenderableText(message);
		const parts = renderable.split('\n');
		return parts.slice(0, maxLines).join('\n');
	}

	function getHiddenLineCount(message: string, maxLines: number = PREVIEW_LINE_LIMIT): number {
		const normalized = normalizeLogText(message);
		const count = normalized.split('\n').length;
		return Math.max(0, count - maxLines);
	}

	function getHiddenCharCount(message: string): number {
		const normalized = normalizeLogText(message);
		return Math.max(0, normalized.length - MAX_RENDER_CHARS);
	}

	function shouldCollapseMessage(message: string): boolean {
		if (!previewCollapsedEnabled) return false;
		return getHiddenLineCount(message) > 0 || getHiddenCharCount(message) > 0;
	}

	function getExpandLabel(message: string): string {
		const hiddenLines = getHiddenLineCount(message);
		const hiddenChars = getHiddenCharCount(message);
		const parts: string[] = [];
		if (hiddenLines > 0) parts.push(`+${hiddenLines} lines`);
		if (hiddenChars > 0) parts.push(`+${hiddenChars} chars`);
		return parts.length > 0 ? `… 더보기 (${parts.join(', ')})` : '… 더보기';
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
		const headerLines: string[] = [];
		headerLines.push(`[Runner] ${runnerId}`);
		if (planFile) {
			const basename = planFile.split(/[\\/]/).pop() ?? planFile;
			headerLines.push(`[Plan] ${basename}`);
		}
		if (engine) headerLines.push(`[Engine] ${engine}`);
		if (branch) headerLines.push(`[Branch] ${branch}`);
		if (worktreePath) headerLines.push(`[Worktree] ${worktreePath}`);
		if (trigger) headerLines.push(`[Trigger] ${trigger}`);
		headerLines.push('---');

		const logLines = lines
			.filter(l => !l.isStale && l.tag !== 'NOISE')
			.map(l => {
				const raw = l.raw;
				return raw.length > 200 ? raw.slice(0, 200) + '…' : raw;
			});

		const text = [...headerLines, ...logLines].join('\n');
		try {
			await navigator.clipboard.writeText(text);
			copied = true;
			setTimeout(() => { copied = false; }, 1500);
		} catch {
			// 클립보드 접근 실패
		}
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

		// FAILURE 태그 감지 → sticky 배너 갱신
		if (parsed.tag === 'FAILURE' && !isStale) {
			failureBanner = { show: true, message: parsed.message };
		}

		pushLine(parsed);
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
				const data = await statusRes.json();
				redisAvailable = data.redis_connected ?? false;
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

		if (apiGate.state !== 'open') {
			connected = 'disconnected';
			redisAvailable = false;
			return;
		}

		// SSE 연결 전 status API로 실행 상태 + Redis 상태 확인
		await fetchStatus();

		eventSource = isMerging
			? devRunnerLogApi.connectMergeStream(runnerId)
			: devRunnerLogApi.connectStream(runnerId, fromLine + lines.length);
		eventSource.onopen = () => {
			connected = 'connected';
			sseStarted = true;
			reconnectCount = 0;
			consecutiveErrors = 0;
		};
		eventSource.onmessage = (event) => {
			// 메인 채널로 흘러오는 merge 종료 신호는 화면에 표시하지 않음
			if (event.data === '__MERGE_COMPLETED__') return;
			addLine(event.data, false);
		};
		// Redis 연결 끊김 이벤트 처리
		eventSource.addEventListener('redis_disconnected', () => {
			redisAvailable = false;
		});
		// Redis 재연결 시 connected 이벤트로 복구
		eventSource.addEventListener('connected', () => {
			redisAvailable = true;
			// running 상태에서 connected 재수신 시 잘못된 exitBanner를 클리어한다.
			// (skip-only 사이클이 FAILED sentinel을 publish한 경우 다음 사이클 시작 전 배너 제거)
			// 진짜 종료 후 stale connected 이벤트로 배너가 사라지는 부작용 방지를 위해 running 조건 사용.
			if (running && exitBanner.show) {
				exitBanner = { show: false, reason: 'completed' };
			}
		});
		// runner 종료 신호 — 배너 표시 후 재연결 중지
		eventSource.addEventListener('completed', (event: MessageEvent) => {
			exitBanner = { show: true, reason: (event as MessageEvent).data || 'completed' };
			eventSource?.close();
			eventSource = null;
			connected = 'disconnected';
		});
		eventSource.onerror = async () => {
			// completed 후 eventSource가 닫혀서 발생한 error면 재연결 중지
			if (exitBanner.show) return;
			consecutiveErrors++;
			eventSource?.close();
			eventSource = null;

			connected = 'disconnected';
			reconnectCount++;

			// Redis 미연결 시 재연결 시도 중단 (서버에서 pubsub 누수 가속 방지)
			const maxRetries = 5;
			if (!redisAvailable && reconnectCount > maxRetries) {
				return; // 수동 새로고침 유도 (배너가 표시됨)
			}

			await fetchStatus();
			setTimeout(connectSSE, getReconnectDelay());
		};
	}

	async function loadFull() {
		try {
			const res = await devRunnerLogApi.full(runnerId, 0, 500);
			if (res.lines.length > 0) {
				lines = res.lines.map((text: string) => parseLine(text, true));
				expandedLongLines = new Set();
			}
		} catch {
			// full 로그 없을 수 있음
		}
	}

	let fromLine = 0;

	async function loadRecent() {
		try {
			const res = await devRunnerLogApi.recent(runnerId, 500);
			fromLine = res.from_line ?? 0;
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
		} catch {
			// 로그 없을 수 있음
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
		} catch {
			// localStorage unavailable in some environments
		}
		await runDiagnostics();
		await loadRecent();
		// 초기 로드 후 스크롤을 맨 아래로 이동
		requestAnimationFrame(() => scrollToBottom());
		if (mode === 'standalone') {
			connectSSE();
		} else {
			// managed 모드: SSE 미연결이므로 fetchStatus()로 redisAvailable 초기화
			await fetchStatus();
		}
	});

	onDestroy(() => {
		if (mode === 'standalone' && eventSource) {
			eventSource.close();
                        if (noiseTimer) clearTimeout(noiseTimer);
			eventSource = null;
		}
	});

	function getTagStyle(tag: string) {
		return tagColors[tag] ?? tagColors.INFO;
	}

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
			addLine(cur ? '[MERGE] 머지 로그 스트림으로 전환...' : '[MERGE] 러너 로그 스트림으로 복귀...', false);
			connectSSE();
		}
		prevMerging = cur;
	});

	// ── managed 모드 공개 API ───────────────────────────────────────────────────

	let _catchUpInProgress = false;
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
		if (mode !== 'managed' || _catchUpInProgress) return;
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
		} finally {
			_pendingInjectBuffer = [];
			_catchUpInProgress = false;
			requestAnimationFrame(() => scrollToBottom());
		}
	}

	export function injectCompleted(reason: string = 'completed') {
		exitBanner = { show: true, reason };
		eventSource?.close();
		eventSource = null;
		connected = 'disconnected';
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
			<span class="text-xs font-medium uppercase tracking-wider text-gray-300">Live Logs</span>
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
				class="h-6 w-6 rounded transition-colors inline-flex items-center justify-center {copied ? 'text-green-400' : 'text-gray-400'} hover:bg-gray-700"
				title="로그 복사 (러너 정보 + 현재 세션 로그)"
				onclick={copyLog}
			>
				{#if copied}
					<!-- Check icon -->
					<svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
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

	<!-- Log Content (Phase 2: text-sm for body) -->
	<div
		bind:this={logContainer}
		onscroll={handleScroll}
		class="flex-1 min-h-0 overflow-y-auto font-mono text-xs p-1.5 bg-gray-950 text-gray-300 dr-scrollbar-thin"
	>
		{#if lines.length === 0}
			<span class="text-gray-600">로그가 없습니다</span>
		{:else}
			{#each lines as line, i}
				{#if line.tag === 'NOISE'}
					<div class="dr-log-line dr-log-line-noise flex items-center py-0 leading-5 {line.isStale ? 'opacity-30' : ''}">
						{#if expandedNoiseIndices.includes(i)}
							<span class="text-gray-600 italic">··· {line.noiseCount} hidden lines ···</span>
							<button
								onclick={() => expandedNoiseIndices = expandedNoiseIndices.filter(n => n !== i)}
								class="ml-2 text-gray-600 hover:text-gray-400"
							>▲</button>
						{:else}
							<button
								onclick={() => expandedNoiseIndices = [...expandedNoiseIndices, i]}
								class="text-gray-600 hover:text-gray-400 italic w-full text-left"
							>··· {line.noiseCount} hidden lines ···</button>
						{/if}
					</div>
				{:else if isSeparator(line.raw)}
					<div class="py-2 text-center select-none opacity-60">
						<span class="text-gray-500 text-[10px]">{extractSeparatorText(line.raw)}</span><!-- separator -->
					</div>
				{:else if line.tag === 'CYCLE'}
					{@const style = getTagStyle(line.tag)}
					{@const cycleExpanded = isExpanded(line.id)}
					{@const cycleCollapsed = shouldCollapseMessage(line.message)}
					<div class="phase-separator {line.isStale ? 'opacity-30' : ''}">
						<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						<span class="font-mono text-[10px] text-muted-foreground whitespace-pre-wrap">
							{cycleCollapsed && !cycleExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
						</span>
						{#if cycleCollapsed}
							<button
								type="button"
								class={getExpandButtonClass(cycleExpanded)}
								aria-expanded={cycleExpanded}
								aria-pressed={cycleExpanded}
								onclick={() => toggleExpand(line.id)}
								onkeydown={(e) => handleExpandKeydown(e, line.id)}
							>
								{cycleExpanded ? '접기' : getExpandLabel(line.message)}
							</button>
						{/if}
					</div>
				{:else if line.tag === 'PHASE'}
					{@const style = getTagStyle(line.tag)}
					{@const phaseExpanded = isExpanded(line.id)}
					{@const phaseCollapsed = shouldCollapseMessage(line.message)}
					<div class="dr-log-line dr-log-line-phase flex items-start gap-2 py-0 leading-5 mt-1.5 border-t border-indigo-900/40 {line.isStale ? 'opacity-30' : ''}">
						<span class="text-xs text-gray-400/60 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="shrink-0 w-[42px] text-right {style.text}">
							<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 break-all text-indigo-300 font-medium whitespace-pre-wrap">
							{phaseCollapsed && !phaseExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
						</span>
						{#if phaseCollapsed}
							<button
								type="button"
								class={getExpandButtonClass(phaseExpanded)}
								aria-expanded={phaseExpanded}
								aria-pressed={phaseExpanded}
								onclick={() => toggleExpand(line.id)}
								onkeydown={(e) => handleExpandKeydown(e, line.id)}
							>
								{phaseExpanded ? '접기' : getExpandLabel(line.message)}
							</button>
						{/if}
					</div>
				{:else if line.tag === 'TOOL'}
					{@const style = getTagStyle(line.tag)}
					{@const toolExpanded = isExpanded(line.id)}
					{@const toolCollapsed = shouldCollapseMessage(line.message)}
					<div class="dr-log-line dr-log-line-tool flex items-start gap-2 py-0 leading-5 opacity-40 {line.isStale ? 'opacity-20' : ''}">
						<span class="text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="shrink-0 w-[42px] text-right {style.text}">
							<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 break-all whitespace-pre-wrap text-gray-500">
							{toolCollapsed && !toolExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
						</span>
						{#if toolCollapsed}
							<button
								type="button"
								class={getExpandButtonClass(toolExpanded)}
								aria-expanded={toolExpanded}
								aria-pressed={toolExpanded}
								onclick={() => toggleExpand(line.id)}
								onkeydown={(e) => handleExpandKeydown(e, line.id)}
							>
								{toolExpanded ? '접기' : getExpandLabel(line.message)}
							</button>
						{/if}
					</div>
				{:else if line.tag === 'RESULT'}
					{@const style = getTagStyle(line.tag)}
					{@const resultMatch = line.message.match(/^(\d+)→\s?(.*)/)}
					{@const resultBody = resultMatch ? resultMatch[2] : line.message}
					{@const resultExpanded = isExpanded(line.id)}
					{@const resultCollapsed = shouldCollapseMessage(resultBody)}
					<div class="dr-log-line dr-log-line-result flex items-start gap-0 py-0 leading-5 opacity-60 {line.isStale ? 'opacity-20' : ''}">
						{#if resultMatch}
							<span class="text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none text-right pr-1">{line.timestamp}</span>
							<span class="shrink-0 w-[42px] text-right {style.text} mr-1">
								<span class="dr-tag-badge {style.bg}">{line.tag}</span>
							</span>
							<span class="flex-1 min-w-0 flex items-baseline bg-gray-900/60 rounded px-1 font-mono">
								<span class="shrink-0 w-[28px] text-right pr-1.5 text-gray-600 tabular-nums select-none text-[10px]">{resultMatch[1]}</span>
								<span class="text-gray-500 select-none text-[10px] pr-1">→</span>
								<span class="flex-1 min-w-0 break-all whitespace-pre-wrap text-emerald-300/80 text-[11px]">
									{resultCollapsed && !resultExpanded ? getPreviewLines(resultBody) : getRenderableText(resultBody)}
								</span>
								{#if resultCollapsed}
									<button
										type="button"
										class={getExpandButtonClass(resultExpanded)}
										aria-expanded={resultExpanded}
										aria-pressed={resultExpanded}
										onclick={() => toggleExpand(line.id)}
										onkeydown={(e) => handleExpandKeydown(e, line.id)}
									>
										{resultExpanded ? '접기' : getExpandLabel(resultBody)}
									</button>
								{/if}
							</span>
						{:else}
							<span class="text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
							<span class="shrink-0 w-[42px] text-right {style.text}">
								<span class="dr-tag-badge {style.bg}">{line.tag}</span>
							</span>
							<span class="flex-1 min-w-0 break-all whitespace-pre-wrap text-gray-400 text-xs">
								{resultCollapsed && !resultExpanded ? getPreviewLines(resultBody) : getRenderableText(resultBody)}
							</span>
							{#if resultCollapsed}
								<button
									type="button"
									class={getExpandButtonClass(resultExpanded)}
									aria-expanded={resultExpanded}
									aria-pressed={resultExpanded}
									onclick={() => toggleExpand(line.id)}
									onkeydown={(e) => handleExpandKeydown(e, line.id)}
								>
									{resultExpanded ? '접기' : getExpandLabel(resultBody)}
								</button>
							{/if}
						{/if}
					</div>
				{:else if line.tag}
					{@const style = getTagStyle(line.tag)}
					{@const lineExpanded = isExpanded(line.id)}
					{@const lineCollapsed = shouldCollapseMessage(line.message)}
					<div class="dr-log-line dr-log-line-{line.tag.toLowerCase()} flex items-start gap-2 py-0 leading-5 {line.isStale ? 'opacity-30' : ''} {line.tag === 'ERROR' ? 'bg-red-950/50 -mx-3 px-3 rounded' : line.tag === 'FAILURE' ? 'bg-red-950/70 border-l-2 border-red-500 -mx-3 px-3 rounded' : line.tag === 'HOLD' ? 'bg-yellow-950/40 border-l-2 border-yellow-500 -mx-3 px-3 rounded' : ''}">
						<span class="text-xs text-gray-400/60 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="shrink-0 w-[42px] text-right {style.text}">
							<span class="dr-tag-badge {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 break-all whitespace-pre-wrap {line.tag === 'FAILURE' ? 'text-red-300 font-bold' : line.tag === 'HOLD' ? 'text-yellow-300 font-bold' : line.tag === 'ERROR' ? 'text-red-400' : line.tag === 'DONE' ? 'text-green-400' : 'text-gray-300'}">
							{lineCollapsed && !lineExpanded ? getPreviewLines(line.message) : getRenderableText(line.message)}
						</span>
						{#if lineCollapsed}
							<button
								type="button"
								class={getExpandButtonClass(lineExpanded)}
								aria-expanded={lineExpanded}
								aria-pressed={lineExpanded}
								onclick={() => toggleExpand(line.id)}
								onkeydown={(e) => handleExpandKeydown(e, line.id)}
							>
								{lineExpanded ? '접기' : getExpandLabel(line.message)}
							</button>
						{/if}
					</div>
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



