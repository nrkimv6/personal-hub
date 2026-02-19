<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { autoNextLogApi } from '$lib/api';

	interface ParsedLine {
		timestamp: string;
		tag: string;
		message: string;
		raw: string;
		isStale: boolean;
	}

	let lines = $state<ParsedLine[]>([]);
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
	let listenerAlive = $state<boolean | null>(null);
	let cliRunning = $state<boolean | null>(null);
	let processPid = $state<number | null>(null);
	const MAX_LINES = 500;
	const SEPARATOR_PATTERN = '════════════════';
	const BASE_DELAY = 3000;

	// Tag colors for dark background
	const tagColors: Record<string, { text: string; bg: string }> = {
		AI: { text: 'text-blue-400', bg: 'bg-blue-500/20' },
		TOOL: { text: 'text-yellow-400', bg: 'bg-yellow-500/20' },
		DONE: { text: 'text-green-400', bg: 'bg-green-500/20' },
		ERROR: { text: 'text-red-400', bg: 'bg-red-500/20' },
		INFO: { text: 'text-gray-500', bg: 'bg-transparent' },
		SYSTEM: { text: 'text-purple-400', bg: 'bg-purple-500/20' },
		WARN: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
		STDERR: { text: 'text-red-400', bg: 'bg-red-500/30' },
		LINE: { text: 'text-gray-600', bg: 'bg-transparent' }
	};

	const LINE_PATTERN = /^\[?(\d{2}:\d{2}:\d{2})\]?\s*\[(\w+)\]\s*(.*)/;

	function parseLine(text: string, isStale: boolean): ParsedLine {
		const match = text.match(LINE_PATTERN);
		if (match) {
			return { timestamp: match[1], tag: match[2], message: match[3], raw: text, isStale };
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
		if (text.includes(SEPARATOR_PATTERN) && !isStale) {
			lines = lines.map((l) => ({ ...l, isStale: true }));
		}

		const parsed = parseLine(text, isStale);

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
		if (!logContainer) return;
		const { scrollTop, scrollHeight, clientHeight } = logContainer;
		const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
		if (!isAtBottom && autoScroll) {
			autoScroll = false;
		}
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
			const statusRes = await fetch('/api/v1/auto-next/status');
			if (statusRes.ok) {
				redisAvailable = true;
				const data = await statusRes.json();
				listenerAlive = data.listener_alive ?? null;
				cliRunning = data.running ?? null;
				processPid = data.pid ?? null;
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

		eventSource = autoNextLogApi.connectStream();
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
			const res = await autoNextLogApi.recent(100);
			lines = res.lines.map((text: string) => parseLine(text, true));
		} catch {
			// 로그 없을 수 있음
		}
	}

	onMount(async () => {
		await loadRecent();
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

	// Max session ID for dimming old sessions
	let maxSessionLine = $derived(
		lines.findLastIndex(l => isSeparator(l.raw) && !l.isStale)
	);
</script>

<div class="flex flex-col h-full">
	<!-- Toolbar -->
	<div class="flex items-center justify-between px-3 py-2 border-b border-gray-700 shrink-0 bg-gray-900">
		<div class="flex items-center gap-2">
			<span class="text-xs font-medium uppercase tracking-wider text-gray-300">Live Logs</span>
			<div class="flex items-center gap-1.5">
				{#if connected === 'connected' && redisAvailable}
					<div class="w-2 h-2 rounded-full bg-green-500"></div>
					<span class="text-[10px] text-green-400">SSE 연결됨</span>
				{:else if connected === 'connected' && !redisAvailable}
					<div class="w-2 h-2 rounded-full bg-yellow-500"></div>
					<span class="text-[10px] text-yellow-400">Redis 미연결</span>
				{:else}
					<div class="w-2 h-2 rounded-full bg-gray-400 animate-pulse"></div>
					<span class="text-[10px] text-gray-500">재연결 중... ({reconnectCount})</span>
				{/if}
			</div>
			{#if listenerAlive !== null}
				{#if listenerAlive && cliRunning}
					<span class="text-[10px] px-1.5 py-0.5 rounded text-cyan-400 bg-cyan-500/20">
						실행 중{processPid ? ` (PID: ${processPid})` : ''}
					</span>
				{:else if listenerAlive}
					<span class="text-[10px] px-1.5 py-0.5 rounded text-green-400 bg-green-500/20">
						대기 중
					</span>
				{:else}
					<span class="text-[10px] px-1.5 py-0.5 rounded text-gray-500 bg-gray-500/20">
						리스너 꺼짐
					</span>
				{/if}
			{/if}
			{#if paused && pauseBuffer.length > 0}
				<span class="text-[10px] text-yellow-400 bg-yellow-500/20 px-1.5 py-0.5 rounded">
					+{pauseBuffer.length} 버퍼
				</span>
			{/if}
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
				{/if}
			</button>
			{#if !autoScroll}
				<button
					class="h-6 px-2 text-[10px] text-gray-500 hover:bg-gray-700 rounded transition-colors inline-flex items-center gap-1"
					onclick={scrollToBottom}
				>
					<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/><line x1="5" y1="19" x2="19" y2="19"/></svg>
					Bottom
				</button>
			{/if}
		</div>
	</div>

	<!-- Log Content -->
	<div
		bind:this={logContainer}
		onscroll={handleScroll}
		class="flex-1 overflow-y-auto font-mono text-xs p-3 bg-gray-950 text-gray-300"
	>
		{#if lines.length === 0}
			<span class="text-gray-600">로그가 없습니다</span>
		{:else}
			{#each lines as line}
				{#if isSeparator(line.raw)}
					<div class="py-2 text-center select-none {line.isStale ? 'opacity-25' : 'opacity-60'}">
						<span class="text-gray-500 text-[10px]">{extractSeparatorText(line.raw)}</span><!-- separator -->
					</div>
				{:else if line.tag}
					{@const style = getTagStyle(line.tag)}
					<div class="flex items-start gap-2 py-0.5 leading-5 {line.isStale ? 'opacity-30' : ''} {line.tag === 'ERROR' ? 'bg-red-950/50 -mx-3 px-3 rounded' : ''}">
						<span class="text-gray-400/60 shrink-0 w-[56px] tabular-nums select-none">{line.timestamp}</span>
						<span class="shrink-0 w-[42px] text-right font-semibold {style.text}">
							<span class="rounded px-1 py-0.5 {style.bg}">{line.tag}</span>
						</span>
						<span class="flex-1 min-w-0 break-all {line.tag === 'ERROR' ? 'text-red-400' : line.tag === 'DONE' ? 'text-green-400' : 'text-gray-300'}">
							{line.message}
						</span>
					</div>
				{:else}
					<div class="py-0.5 leading-5 {line.isStale ? 'opacity-30' : ''} text-gray-400 break-all whitespace-pre-wrap">
						{line.raw}
					</div>
				{/if}
			{/each}
		{/if}
	</div>
</div>
