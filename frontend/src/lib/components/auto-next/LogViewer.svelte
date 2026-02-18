<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { autoNextLogApi } from '$lib/api';

	interface LogLine {
		text: string;
		isStale: boolean;
	}

	let lines = $state<LogLine[]>([]);
	let connected = $state(false);
	// Phase 4: autoScroll 상태 유지 (Pause/Resume + Bottom 버튼으로 제어)
	let autoScroll = $state(true);
	// Phase 4: Pause/Resume 상태
	let paused = $state(false);
	let pauseBuffer = $state<LogLine[]>([]);
	let logContainer: HTMLDivElement;
	let eventSource: EventSource | null = null;
	let sseStarted = $state(false);
	let reconnectCount = $state(0);
	let sseError = $state<string | null>(null);

	const MAX_LINES = 500;
	const SEPARATOR_PATTERN = '════════════════';
	const MAX_RECONNECT = 10;
	const BASE_DELAY = 5000;

	function addLine(text: string, isStale: boolean) {
		// 구분자 감지 시 이전 라인을 모두 stale로 전환
		if (text.includes(SEPARATOR_PATTERN) && !isStale) {
			lines = lines.map((l) => ({ ...l, isStale: true }));
		}

		// Phase 4: paused 상태면 버퍼에 저장
		if (paused && !isStale) {
			pauseBuffer.push({ text, isStale });
			return;
		}

		lines.push({ text, isStale });
		if (lines.length > MAX_LINES) {
			lines = lines.slice(lines.length - MAX_LINES);
		}
		if (autoScroll && logContainer) {
			requestAnimationFrame(() => {
				logContainer.scrollTop = logContainer.scrollHeight;
			});
		}
	}

	// Phase 4: Resume 시 버퍼 일괄 반영
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

	// Phase 4: 맨 아래로 스크롤
	function scrollToBottom() {
		if (logContainer) {
			logContainer.scrollTop = logContainer.scrollHeight;
			autoScroll = true;
		}
	}

	function getReconnectDelay() {
		// Exponential backoff: 5s, 10s, 20s, 40s, 60s (max)
		return Math.min(BASE_DELAY * Math.pow(2, reconnectCount), 60000);
	}

	function manualReconnect() {
		reconnectCount = 0;
		sseError = null;
		connectSSE();
	}

	function connectSSE() {
		if (eventSource) eventSource.close();

		eventSource = autoNextLogApi.connectStream();
		eventSource.onopen = () => {
			connected = true;
			sseStarted = true;
			reconnectCount = 0;
			sseError = null;
		};
		eventSource.onmessage = (event) => {
			addLine(event.data, false);
		};
		eventSource.onerror = () => {
			connected = false;
			eventSource?.close();
			eventSource = null;

			if (reconnectCount >= MAX_RECONNECT) {
				sseError = 'SSE 연결 실패 (최대 재시도 초과)';
				return;
			}

			reconnectCount++;
			setTimeout(connectSSE, getReconnectDelay());
		};
	}

	async function loadRecent() {
		try {
			const res = await autoNextLogApi.recent(100);
			// 초기 로드된 라인은 모두 stale (이전 로그)
			lines = res.lines.map((text: string) => ({ text, isStale: true }));
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

	// Phase 4: 구분자 라인 여부 감지 함수
	function isSeparator(text: string): boolean {
		return text.includes(SEPARATOR_PATTERN);
	}

	// 구분자에서 세션 정보 텍스트 추출
	function extractSeparatorText(text: string): string {
		// 구분자 패턴 제거 후 남은 텍스트 정리
		return text.replace(/[═=\s]+/g, ' ').trim() || '새 세션';
	}
</script>

<!-- Phase 4: 외부 컨테이너를 flex column h-full로 변경 -->
<div class="bg-white rounded-lg border flex flex-col h-full">
	<div class="p-3 border-b flex items-center justify-between shrink-0">
		<div class="flex items-center gap-2">
			<h2 class="font-semibold text-sm">로그</h2>
			{#if connected}
				<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">
					<span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>
					연결됨
				</span>
			{:else if sseError}
				<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">
					<span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>
					{sseError}
				</span>
				<button
					onclick={manualReconnect}
					class="px-2 py-0.5 text-xs bg-blue-500 text-white rounded hover:bg-blue-600"
				>
					수동 재연결
				</button>
			{:else}
				<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">
					<span class="w-1.5 h-1.5 rounded-full bg-gray-400"></span>
					끊김 (재시도 {reconnectCount}/{MAX_RECONNECT})
				</span>
			{/if}
			{#if paused && pauseBuffer.length > 0}
				<span class="text-xs text-yellow-600 bg-yellow-50 px-2 py-0.5 rounded">
					+{pauseBuffer.length} 버퍼
				</span>
			{/if}
		</div>
		<!-- Phase 4: Pause/Resume + Bottom 버튼 (checkbox 대체) -->
		<div class="flex items-center gap-1">
			<button
				onclick={() => paused ? resumeLog() : (paused = true)}
				class="px-2 py-1 text-xs rounded transition-colors {paused ? 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
				title={paused ? 'Resume: 버퍼된 로그를 일괄 반영합니다' : 'Pause: 화면 업데이트를 일시 중지합니다'}
			>
				{paused ? '▶ Resume' : '⏸ Pause'}
			</button>
			<button
				onclick={scrollToBottom}
				class="px-2 py-1 text-xs rounded bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
				title="맨 아래로 스크롤"
			>
				↓ Bottom
			</button>
		</div>
	</div>
	<!-- Phase 4: h-64 → flex-1 min-h-0 -->
	<div
		bind:this={logContainer}
		class="flex-1 min-h-0 overflow-y-auto bg-gray-900 text-gray-200 text-xs font-mono p-3 leading-5"
	>
		{#if lines.length === 0}
			<span class="text-gray-500">로그가 없습니다</span>
		{:else}
			{#each lines as line}
				{#if isSeparator(line.text)}
					<!-- Phase 4: 세션 구분자를 가운데 정렬 텍스트로 렌더링 -->
					<div class="text-center text-gray-500 text-xs py-2 border-y border-gray-700 my-1">
						{extractSeparatorText(line.text)}
					</div>
				{:else}
					{@const tagColor = line.isStale ? '' :
						line.text.includes('[AI]') ? 'text-cyan-400' :
						line.text.includes('[TOOL]') ? 'text-yellow-400' :
						line.text.includes('[DONE]') ? 'text-green-400' :
						line.text.includes('[ERROR]') ? 'text-red-400' : ''}
					<div
						class="whitespace-pre-wrap break-all {line.isStale ? 'opacity-40 text-gray-500' : tagColor}"
					>
						{line.text}
					</div>
				{/if}
			{/each}
		{/if}
	</div>
</div>
