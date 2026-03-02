<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerMergeApi, type MergeQueueItem, type MergeHistoryItem } from '$lib/api/dev-runner';

	let items: MergeQueueItem[] = $state([]);
	let historyItems: MergeHistoryItem[] = $state([]);
	let loading = $state(false);
	let error = $state('');
	let actionLoading: Record<string, boolean> = $state({});

	// 로그뷰 state
	let selectedRunnerId: string | null = $state(null);
	let mergeLogLines: { tag: string; message: string }[] = $state([]);
	let mergeEventSource: EventSource | null = $state(null);

	const STATUS_LABEL: Record<string, string> = {
		pending: '대기',
		merging: '머지 중',
		testing: '테스트 중',
		fixing: '수정 중',
		done: '완료',
		failed: '실패',
	};

	const STATUS_CLASS: Record<string, string> = {
		pending: 'bg-yellow-100 text-yellow-800',
		merging: 'bg-blue-100 text-blue-800',
		testing: 'bg-purple-100 text-purple-800',
		fixing: 'bg-orange-100 text-orange-800',
		done: 'bg-green-100 text-green-800',
		failed: 'bg-red-100 text-red-800',
	};

	const TAG_CLASS: Record<string, string> = {
		COMMIT: 'text-blue-400',
		MERGE: 'text-green-400',
		TEST: 'text-purple-400',
		ERROR: 'text-red-400',
		DONE: 'text-emerald-400',
	};

	async function load() {
		loading = true;
		error = '';
		try {
			[items, historyItems] = await Promise.all([
				devRunnerMergeApi.queue(),
				devRunnerMergeApi.history(),
			]);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '불러오기 실패';
		} finally {
			loading = false;
		}
	}

	async function handleRetry(runnerId: string) {
		actionLoading = { ...actionLoading, [`retry-${runnerId}`]: true };
		try {
			await devRunnerMergeApi.retry(runnerId);
			await load();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '재시도 실패';
		} finally {
			const next = { ...actionLoading };
			delete next[`retry-${runnerId}`];
			actionLoading = next;
		}
	}

	async function handleRevert(runnerId: string) {
		actionLoading = { ...actionLoading, [`revert-${runnerId}`]: true };
		try {
			await devRunnerMergeApi.revert(runnerId);
			await load();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '되돌리기 실패';
		} finally {
			const next = { ...actionLoading };
			delete next[`revert-${runnerId}`];
			actionLoading = next;
		}
	}

	function planName(item: MergeQueueItem | MergeHistoryItem): string {
		if (!item.plan_file) return item.project || item.runner_id;
		const parts = item.plan_file.replace(/\\/g, '/').split('/');
		return parts[parts.length - 1] || item.runner_id;
	}

	function connectMergeLog(runnerId: string) {
		mergeEventSource?.close();
		mergeLogLines = [];
		const es = new EventSource(`/api/dev-runner/merge-log/stream?runner_id=${runnerId}`);
		es.onmessage = (e) => {
			const match = e.data.match(/^\[MERGE\]\[(\w+)\] (.+)$/);
			if (match) {
				mergeLogLines = [...mergeLogLines, { tag: match[1], message: match[2] }].slice(-200);
			}
		};
		es.addEventListener('completed', () => es.close());
		mergeEventSource = es;
	}

	let pollInterval: ReturnType<typeof setInterval>;

	onMount(() => {
		load();
		pollInterval = setInterval(load, 5000);
	});

	onDestroy(() => {
		clearInterval(pollInterval);
		mergeEventSource?.close();
	});
</script>

<div class="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
	<div class="mb-3 flex items-center justify-between">
		<h3 class="text-sm font-semibold text-gray-700">Merge Queue</h3>
		<button
			onclick={load}
			class="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 disabled:opacity-50"
			disabled={loading}
		>
			{loading ? '새로고침 중...' : '새로고침'}
		</button>
	</div>

	{#if error}
		<p class="text-xs text-red-500">{error}</p>
	{/if}

	{#if items.length === 0 && !loading}
		<p class="text-center text-xs text-gray-400">대기 중인 머지 요청 없음</p>
	{:else}
		<div class="space-y-2">
			{#each items as item (item.runner_id)}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_interactive_supports_focus -->
				<div
					class="rounded border bg-gray-50 p-3 cursor-pointer {selectedRunnerId === item.runner_id ? 'border-blue-300 bg-blue-50' : 'border-gray-100'}"
					role="button"
					onclick={() => { selectedRunnerId = item.runner_id; connectMergeLog(item.runner_id); }}
				>
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0 flex-1">
							<p class="truncate text-xs font-medium text-gray-800">{planName(item)}</p>
							<p class="truncate text-xs text-gray-400">{item.project} · {item.branch}</p>
							<p class="text-xs text-gray-400">{item.timestamp.slice(0, 16).replace('T', ' ')}</p>
						</div>
						<div class="flex flex-col items-end gap-1">
							<span
								class="rounded px-2 py-0.5 text-xs font-medium {STATUS_CLASS[item.status] ?? 'bg-gray-100 text-gray-700'}"
							>
								{STATUS_LABEL[item.status] ?? item.status}
							</span>
							{#if item.status === 'failed'}
								<div class="flex gap-1">
									<button
										onclick={(e) => { e.stopPropagation(); handleRetry(item.runner_id); }}
										disabled={actionLoading[`retry-${item.runner_id}`]}
										class="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-600 hover:bg-blue-100 disabled:opacity-50"
									>
										재시도
									</button>
									<button
										onclick={(e) => { e.stopPropagation(); handleRevert(item.runner_id); }}
										disabled={actionLoading[`revert-${item.runner_id}`]}
										class="rounded bg-red-50 px-2 py-0.5 text-xs text-red-600 hover:bg-red-100 disabled:opacity-50"
									>
										되돌리기
									</button>
								</div>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}

	{#if historyItems.length > 0}
		<hr class="my-3 border-gray-100" />
		<p class="mb-2 text-center text-xs text-gray-300">— 실행 이력 —</p>
		<div class="space-y-2">
			{#each historyItems as item (item.runner_id)}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_interactive_supports_focus -->
				<div
					class="rounded border border-gray-100 bg-gray-50 p-3 opacity-40 grayscale cursor-pointer {selectedRunnerId === item.runner_id ? 'border-blue-300' : ''}"
					role="button"
					onclick={() => { selectedRunnerId = item.runner_id; connectMergeLog(item.runner_id); }}
				>
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0 flex-1">
							<p class="truncate text-xs font-medium text-gray-800">{planName(item)}</p>
							<p class="truncate text-xs text-gray-400">{item.project} · {item.branch}</p>
							<p class="text-xs text-gray-400">{item.timestamp.slice(0, 16).replace('T', ' ')}</p>
						</div>
						<div class="flex items-center gap-1">
							{#if item.status === 'done'}
								<span class="text-green-600 text-xs font-bold">✓</span>
							{:else if item.status === 'failed'}
								<span class="text-red-600 text-xs font-bold">✗</span>
							{/if}
							<span class="rounded px-2 py-0.5 text-xs font-medium {STATUS_CLASS[item.status] ?? 'bg-gray-100 text-gray-700'}">
								{STATUS_LABEL[item.status] ?? item.status}
							</span>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}

	{#if selectedRunnerId}
		<div class="mt-3 rounded bg-gray-900 p-3 font-mono text-xs text-gray-200 overflow-y-auto max-h-[400px]">
			{#if mergeLogLines.length === 0}
				<p class="text-gray-500">로그 대기 중...</p>
			{:else}
				{#each mergeLogLines as line}
					<div>
						<span class={TAG_CLASS[line.tag] ?? 'text-gray-300'}>[{line.tag}]</span>
						<span class="ml-1 text-gray-200">{line.message}</span>
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>
