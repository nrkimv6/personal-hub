<script>
	import { onMount, onDestroy } from 'svelte';

	let status = $state('unknown'); // 'connected', 'disconnected', 'unknown'
	let health = $state(null);
	let error = $state(null);
	let checkInterval = null;

	async function checkHealth() {
		try {
			const response = await fetch('/api/v1/mobile/health', {
				signal: AbortSignal.timeout(5000)
			});

			if (response.ok) {
				health = await response.json();
				status = 'connected';
				error = null;
			} else {
				status = 'disconnected';
				error = '모바일 서버 응답 오류';
				health = null;
			}
		} catch (err) {
			status = 'disconnected';
			error = err.name === 'TimeoutError' ? '연결 시간 초과' : '서버 연결 불가';
			health = null;
		}
	}

	onMount(() => {
		checkHealth();
		checkInterval = setInterval(checkHealth, 30000); // 30초마다 체크
	});

	onDestroy(() => {
		if (checkInterval) {
			clearInterval(checkInterval);
		}
	});

	function getStatusBadgeClass() {
		switch (status) {
			case 'connected':
				return 'badge-success';
			case 'disconnected':
				return 'badge-error';
			default:
				return 'badge-ghost';
		}
	}

	function getStatusText() {
		switch (status) {
			case 'connected':
				return '연결됨';
			case 'disconnected':
				return '연결 끊김';
			default:
				return '확인 중...';
		}
	}
</script>

<div class="flex items-center gap-2">
	<div class="tooltip" data-tip={error || '모바일 서버 상태'}>
		<div class="badge {getStatusBadgeClass()} gap-1">
			{#if status === 'connected'}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					class="h-3 w-3"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
				>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
				</svg>
			{:else if status === 'disconnected'}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					class="h-3 w-3"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M6 18L18 6M6 6l12 12"
					/>
				</svg>
			{:else}
				<span class="loading loading-spinner loading-xs"></span>
			{/if}
			<span class="text-xs">모바일 서버: {getStatusText()}</span>
		</div>
	</div>

	{#if health && status === 'connected'}
		<div class="text-xs text-gray-500">
			가동시간: {health.uptime_human || 'N/A'}
		</div>
	{/if}
</div>
