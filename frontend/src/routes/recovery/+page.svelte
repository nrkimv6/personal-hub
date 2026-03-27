<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	interface ApiStatus {
		port: number;
		up: boolean;
		error: string | null;
	}

	interface StatusData {
		wmi: { healthy: boolean; error: string | null };
		api: {
			public: ApiStatus;
			admin: ApiStatus;
		};
		timestamp: string;
	}

	let status: StatusData | null = $state(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let actionLoading = $state<string | null>(null);
	let actionMessage = $state<string | null>(null);
	let actionSuccess = $state<boolean | null>(null);

	let pollTimer: ReturnType<typeof setInterval> | null = null;

	async function fetchStatus() {
		try {
			const res = await fetch('/recovery');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			status = await res.json();
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	async function doAction(action: string) {
		actionLoading = action;
		actionMessage = null;
		actionSuccess = null;
		try {
			const res = await fetch('/recovery', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action })
			});
			const data = await res.json();
			actionSuccess = data.success;
			actionMessage = data.message ?? (data.success ? '완료' : data.error ?? '오류 발생');
			// 상태 즉시 갱신
			await fetchStatus();
		} catch (e) {
			actionSuccess = false;
			actionMessage = e instanceof Error ? e.message : String(e);
		} finally {
			actionLoading = null;
		}
	}

	onMount(() => {
		fetchStatus();
		pollTimer = setInterval(fetchStatus, 5000);
	});

	onDestroy(() => {
		if (pollTimer !== null) clearInterval(pollTimer);
	});

	function statusColor(ok: boolean | undefined) {
		if (ok === undefined) return 'text-gray-400';
		return ok ? 'text-green-400' : 'text-red-400';
	}

	function statusLabel(ok: boolean | undefined) {
		if (ok === undefined) return '확인 중';
		return ok ? '정상' : '다운';
	}

	function formatTime(iso: string | undefined) {
		if (!iso) return '-';
		return new Date(iso).toLocaleTimeString('ko-KR');
	}
</script>

<svelte:head>
	<title>긴급 복구 — Monitor Page</title>
</svelte:head>

<div class="min-h-screen bg-gray-950 text-gray-100 flex flex-col items-center justify-start py-12 px-4">
	<div class="w-full max-w-xl">
		<div class="mb-8 text-center">
			<h1 class="text-2xl font-bold text-white mb-1">🛠 긴급 복구</h1>
			<p class="text-gray-400 text-sm">API가 다운되어도 이 페이지는 SvelteKit dev 서버를 통해 동작합니다.</p>
		</div>

		<!-- 상태 카드 -->
		<div class="bg-gray-900 rounded-xl border border-gray-700 p-6 mb-6 space-y-4">
			<div class="flex items-center justify-between mb-2">
				<span class="text-sm font-medium text-gray-300">시스템 상태</span>
				{#if loading}
					<span class="text-xs text-gray-500">로딩 중…</span>
				{:else if status}
					<span class="text-xs text-gray-500">최종 갱신: {formatTime(status.timestamp)} (5초마다 자동)</span>
				{/if}
			</div>

			{#if error}
				<div class="text-red-400 text-sm bg-red-900/30 rounded-lg p-3">
					상태 조회 실패: {error}
				</div>
			{:else if status}
				<!-- WMI -->
				<div class="flex items-center justify-between py-2 border-b border-gray-800">
					<div>
						<span class="text-sm font-medium">WMI 서비스</span>
						{#if status.wmi.error}
							<p class="text-xs text-gray-500 mt-0.5">{status.wmi.error}</p>
						{/if}
					</div>
					<span class="text-sm font-bold {statusColor(status.wmi.healthy)}">
						{statusLabel(status.wmi.healthy)}
					</span>
				</div>
				<!-- API Public -->
				<div class="flex items-center justify-between py-2 border-b border-gray-800">
					<div>
						<span class="text-sm font-medium">API Public (8000)</span>
						{#if status.api.public.error}
							<p class="text-xs text-gray-500 mt-0.5">{status.api.public.error}</p>
						{/if}
					</div>
					<span class="text-sm font-bold {statusColor(status.api.public.up)}">
						{statusLabel(status.api.public.up)}
					</span>
				</div>
				<!-- API Admin -->
				<div class="flex items-center justify-between py-2">
					<div>
						<span class="text-sm font-medium">API Admin (8001)</span>
						{#if status.api.admin.error}
							<p class="text-xs text-gray-500 mt-0.5">{status.api.admin.error}</p>
						{/if}
					</div>
					<span class="text-sm font-bold {statusColor(status.api.admin.up)}">
						{statusLabel(status.api.admin.up)}
					</span>
				</div>
			{:else}
				<div class="text-gray-500 text-sm text-center py-4">상태를 불러오는 중…</div>
			{/if}
		</div>

		<!-- 액션 피드백 -->
		{#if actionMessage}
			<div class="mb-4 rounded-lg px-4 py-3 text-sm {actionSuccess ? 'bg-green-900/40 text-green-300 border border-green-700' : 'bg-red-900/40 text-red-300 border border-red-700'}">
				{actionMessage}
			</div>
		{/if}

		<!-- 액션 버튼 -->
		<div class="space-y-3">
			<button
				class="w-full rounded-xl bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 transition-colors flex items-center justify-center gap-2"
				disabled={actionLoading !== null}
				onclick={() => doAction('restart-wmi')}
			>
				{#if actionLoading === 'restart-wmi'}
					<span class="animate-spin">⏳</span> WMI 재시작 중…
				{:else}
					⚡ WMI 재시작 (winmgmt)
				{/if}
			</button>

			<button
				class="w-full rounded-xl bg-blue-700 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 transition-colors flex items-center justify-center gap-2"
				disabled={actionLoading !== null}
				onclick={() => fetchStatus()}
			>
				🔄 지금 새로고침
			</button>
		</div>

		<p class="mt-8 text-center text-xs text-gray-600">
			Admin 전용 페이지 — SvelteKit dev 서버(:6101)에서만 동작합니다.
		</p>
	</div>
</div>
