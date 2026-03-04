<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { devRunnerMergeApi } from '$lib/api/dev-runner';

	// merge-wait-queue 항목 (lock 대기 중인 runner_id 목록)
	let waitItems: { runner_id: string; status: string }[] = $state([]);
	let loading = $state(false);
	let error = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			const raw = await devRunnerMergeApi.queue();
			// API는 {runner_id, status} 형식 반환 (merge-wait-queue 기반)
			waitItems = raw as unknown as { runner_id: string; status: string }[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '불러오기 실패';
		} finally {
			loading = false;
		}
	}

	let pollInterval: ReturnType<typeof setInterval>;

	onMount(() => {
		load();
		pollInterval = setInterval(load, 5000);
	});

	onDestroy(() => {
		clearInterval(pollInterval);
	});
</script>

<div class="mt-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
	<div class="mb-3 flex items-center justify-between">
		<h3 class="text-sm font-semibold text-gray-700">Merge 대기 큐</h3>
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

	{#if waitItems.length === 0 && !loading}
		<p class="text-center text-xs text-gray-400">merge lock 대기 중인 runner 없음</p>
	{:else}
		<div class="space-y-2">
			{#each waitItems as item (item.runner_id)}
				<div class="rounded border border-gray-100 bg-gray-50 p-3">
					<div class="flex items-center justify-between gap-2">
						<p class="truncate text-xs font-medium text-gray-800 font-mono">{item.runner_id}</p>
						<span class="rounded bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800">
							{item.status}
						</span>
					</div>
					<p class="mt-1 text-xs text-gray-400">merge 로그는 runner 탭에서 확인하세요</p>
				</div>
			{/each}
		</div>
	{/if}

	<p class="mt-3 text-center text-xs text-gray-300">
		merge 진행 로그는 각 runner 탭에서 <code class="font-mono">[MERGE]</code> 태그로 확인
	</p>
</div>
