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

	interface ProcessWatchItem {
		captured_at: string;
		pid: number;
		ppid: number | null;
		parent_name: string;
		name: string;
		cmdline: string;
		cmdline_hash: string;
		create_time: number | null;
		memory_mb: number;
		is_orphan: boolean;
		scope: string;
	}

	interface ProcessWatchData {
		captured_at: string | null;
		source: string;
		snapshot_age_seconds: number | null;
		stale: boolean;
		item_count: number;
		items: ProcessWatchItem[];
		error?: string | null;
		transport?: string;
	}

	let status: StatusData | null = $state(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let actionLoading = $state<string | null>(null);
	let actionMessage = $state<string | null>(null);
	let actionSuccess = $state<boolean | null>(null);

	let watchData = $state<ProcessWatchData | null>(null);
	let watchLoading = $state(false);
	let watchError = $state<string | null>(null);
	let killReasons = $state<Record<number, string>>({});

	let adminToken = $state('');
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	function authHeaders(withJson = false): HeadersInit {
		const headers: Record<string, string> = {};
		if (withJson) headers['Content-Type'] = 'application/json';
		const token = adminToken.trim();
		if (token) headers['x-recovery-admin-token'] = token;
		return headers;
	}

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

	async function fetchProcessWatch() {
		watchLoading = true;
		try {
			const res = await fetch('/recovery/process-watch?min_mb=256&limit=40', {
				headers: authHeaders()
			});
			const data = await res.json();
			if (!res.ok) throw new Error(data?.message ?? `HTTP ${res.status}`);
			watchData = data;
			watchError = null;
		} catch (e) {
			watchError = e instanceof Error ? e.message : String(e);
		} finally {
			watchLoading = false;
		}
	}

	async function doAction(action: string) {
		actionLoading = action;
		actionMessage = null;
		actionSuccess = null;
		try {
			const res = await fetch('/recovery', {
				method: 'POST',
				headers: authHeaders(true),
				body: JSON.stringify({ action })
			});
			const data = await res.json();
			actionSuccess = res.ok && data.success;
			actionMessage = data.message ?? (data.success ? '완료' : data.error ?? '오류 발생');
			await fetchStatus();
		} catch (e) {
			actionSuccess = false;
			actionMessage = e instanceof Error ? e.message : String(e);
		} finally {
			actionLoading = null;
		}
	}

	async function killProcess(item: ProcessWatchItem) {
		const reason = (killReasons[item.pid] ?? '').trim();
		if (reason.length < 8) {
			actionSuccess = false;
			actionMessage = '종료 사유는 최소 8자 이상이어야 합니다.';
			return;
		}

		actionLoading = `kill-${item.pid}`;
		actionMessage = null;
		actionSuccess = null;
		try {
			const res = await fetch('/recovery/process-kill', {
				method: 'POST',
				headers: authHeaders(true),
				body: JSON.stringify({
					pid: item.pid,
					expected_create_time: item.create_time,
					expected_cmdline_hash: item.cmdline_hash,
					reason,
					force: item.scope !== 'monitor_page'
				})
			});
			const data = await res.json();
			actionSuccess = res.ok && data.success;
			actionMessage = data.message ?? data.detail?.message ?? `HTTP ${res.status}`;
			if (res.ok && data.success) {
				await fetchProcessWatch();
			}
		} catch (e) {
			actionSuccess = false;
			actionMessage = e instanceof Error ? e.message : String(e);
		} finally {
			actionLoading = null;
		}
	}

	onMount(() => {
		try {
			adminToken = localStorage.getItem('recovery_admin_token') ?? '';
		} catch {
			adminToken = '';
		}

		fetchStatus();
		fetchProcessWatch();
		pollTimer = setInterval(() => {
			fetchStatus();
			fetchProcessWatch();
		}, 5000);
	});

	$effect(() => {
		try {
			localStorage.setItem('recovery_admin_token', adminToken.trim());
		} catch {
			// noop
		}
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

	function formatTime(iso: string | undefined | null) {
		if (!iso) return '-';
		return new Date(iso).toLocaleTimeString('ko-KR');
	}
</script>

<svelte:head>
	<title>긴급 복구 — Monitor Page</title>
</svelte:head>

<div class="min-h-screen bg-gray-950 text-gray-100 flex flex-col items-center justify-start py-12 px-4">
	<div class="w-full max-w-6xl">
		<div class="mb-8 text-center">
			<h2 class="text-2xl font-bold text-white mb-1">🛠 긴급 복구</h2>
			<p class="text-gray-400 text-sm">6101에서 process-watch 폴백 조회/종료를 수행합니다.</p>
		</div>

		<div class="bg-gray-900 rounded-xl border border-gray-700 p-4 mb-4">
			<div class="text-xs text-gray-400 mb-2">관리자 토큰 (선택, 쿠키 인증 대체)</div>
			<input
				class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100"
				placeholder="RECOVERY_ADMIN_TOKEN"
				bind:value={adminToken}
			/>
		</div>

		<div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
			<div class="bg-gray-900 rounded-xl border border-gray-700 p-6 space-y-4">
				<div class="flex items-center justify-between mb-2">
					<span class="text-sm font-medium text-gray-300">시스템 상태</span>
					{#if loading}
						<span class="text-xs text-gray-500">로딩 중…</span>
					{:else if status}
						<span class="text-xs text-gray-500">최종 갱신: {formatTime(status.timestamp)}</span>
					{/if}
				</div>

				{#if error}
					<div class="text-red-400 text-sm bg-red-900/30 rounded-lg p-3">상태 조회 실패: {error}</div>
				{:else if status}
					<div class="flex items-center justify-between py-2 border-b border-gray-800">
						<div>
							<span class="text-sm font-medium">WMI 서비스</span>
							{#if status.wmi.error}<p class="text-xs text-gray-500 mt-0.5">{status.wmi.error}</p>{/if}
						</div>
						<span class="text-sm font-bold {statusColor(status.wmi.healthy)}">{statusLabel(status.wmi.healthy)}</span>
					</div>
					<div class="flex items-center justify-between py-2 border-b border-gray-800">
						<div>
							<span class="text-sm font-medium">API Public (8000)</span>
							{#if status.api.public.error}<p class="text-xs text-gray-500 mt-0.5">{status.api.public.error}</p>{/if}
						</div>
						<span class="text-sm font-bold {statusColor(status.api.public.up)}">{statusLabel(status.api.public.up)}</span>
					</div>
					<div class="flex items-center justify-between py-2">
						<div>
							<span class="text-sm font-medium">API Admin (8001)</span>
							{#if status.api.admin.error}<p class="text-xs text-gray-500 mt-0.5">{status.api.admin.error}</p>{/if}
						</div>
						<span class="text-sm font-bold {statusColor(status.api.admin.up)}">{statusLabel(status.api.admin.up)}</span>
					</div>
				{/if}

				<div class="space-y-2 pt-2">
					<button
						class="w-full rounded-xl bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 text-white font-semibold py-3 px-4 transition-colors"
						disabled={actionLoading !== null}
						onclick={() => doAction('restart-wmi')}
					>
						{#if actionLoading === 'restart-wmi'}WMI 재시작 중…{:else}⚡ WMI 재시작 (winmgmt){/if}
					</button>
					<button
						class="w-full rounded-xl bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white font-semibold py-3 px-4 transition-colors"
						disabled={actionLoading !== null}
						onclick={() => {
							fetchStatus();
							fetchProcessWatch();
						}}
					>
						🔄 지금 새로고침
					</button>
				</div>
			</div>

			<div class="bg-gray-900 rounded-xl border border-gray-700 p-4">
				<div class="flex items-center justify-between mb-2">
					<div class="text-sm font-medium text-gray-300">Process Watch</div>
					{#if watchData}
						<div class="text-xs text-gray-500">
							source={watchData.source} · age={watchData.snapshot_age_seconds ?? '-'}s · {watchData.transport ?? '-'}
						</div>
					{/if}
				</div>

				{#if watchError}
					<div class="mb-2 text-xs text-red-300 bg-red-900/30 rounded p-2">{watchError}</div>
				{/if}

				{#if watchLoading}
					<div class="text-xs text-gray-500 py-4 text-center">로딩 중…</div>
				{:else if watchData && watchData.items.length > 0}
					<div class="overflow-auto max-h-[520px] rounded border border-gray-800">
						<table class="w-full text-[11px]">
							<thead class="bg-gray-950 sticky top-0">
								<tr class="text-gray-400 border-b border-gray-800">
									<th class="px-2 py-2 text-left">PID</th>
									<th class="px-2 py-2 text-right">메모리</th>
									<th class="px-2 py-2 text-left">부모</th>
									<th class="px-2 py-2 text-left">scope</th>
									<th class="px-2 py-2 text-left">사유</th>
									<th class="px-2 py-2 text-center">종료</th>
								</tr>
							</thead>
							<tbody>
								{#each watchData.items as item}
									<tr class="border-b border-gray-800/60 hover:bg-gray-800/40">
										<td class="px-2 py-2 font-mono">{item.pid}</td>
										<td class="px-2 py-2 text-right font-mono {item.memory_mb >= 1024 ? 'text-red-300' : item.memory_mb >= 512 ? 'text-yellow-300' : 'text-gray-200'}">
											{item.memory_mb.toFixed(1)}MB
										</td>
										<td class="px-2 py-2 text-gray-300">
											PPID {item.ppid ?? '-'} {item.parent_name ? `(${item.parent_name})` : ''}
											{#if item.is_orphan}<span class="ml-1 text-red-300">orphan</span>{/if}
										</td>
										<td class="px-2 py-2">{item.scope}</td>
										<td class="px-2 py-2">
											<input
												class="w-44 rounded border border-gray-700 bg-gray-950 px-2 py-1 text-[11px]"
												placeholder="종료 사유 (8자+)"
												value={killReasons[item.pid] ?? ''}
												oninput={(e) => {
													killReasons = { ...killReasons, [item.pid]: (e.currentTarget as HTMLInputElement).value };
												}}
											/>
										</td>
										<td class="px-2 py-2 text-center">
											<button
												class="rounded bg-red-700 hover:bg-red-600 px-2 py-1 text-[11px] text-white disabled:opacity-50"
												disabled={actionLoading !== null}
												onclick={() => killProcess(item)}
											>
												종료
											</button>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="text-xs text-gray-500 py-4 text-center">표시할 스냅샷이 없습니다.</div>
				{/if}
			</div>
		</div>

		{#if actionMessage}
			<div class="mt-4 rounded-lg px-4 py-3 text-sm {actionSuccess ? 'bg-green-900/40 text-green-300 border border-green-700' : 'bg-red-900/40 text-red-300 border border-red-700'}">
				{actionMessage}
			</div>
		{/if}

		<p class="mt-8 text-center text-xs text-gray-600">
			로컬/관리자 전용 조치 경로. 원격 요청은 차단됩니다.
		</p>
	</div>
</div>
