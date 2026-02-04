<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	let runs = $state([]);
	let loading = $state(true);
	let error = $state(null);

	// 필터
	let statusFilter = $state('all'); // 'all', 'completed', 'failed'
	let targetFilter = $state(null);
	let targets = $state([]);

	async function loadData() {
		try {
			loading = true;

			// 대상 목록 로드
			const targetsRes = await fetch('/api/v1/mobile/targets');
			if (targetsRes.ok) {
				targets = await targetsRes.json();
			}

			// Mock 실행 이력 데이터
			// 실제로는 /api/v1/mobile/runs 같은 API를 호출해야 함
			runs = generateMockRuns();
		} catch (err) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function generateMockRuns() {
		const statuses = ['completed', 'completed', 'completed', 'failed', 'completed'];
		const mockRuns = [];

		for (let i = 0; i < 15; i++) {
			const status = statuses[i % statuses.length];
			const target = targets[i % Math.max(targets.length, 1)] || { id: 1, name: 'Mock 대상' };

			mockRuns.push({
				id: i + 1,
				target_id: target.id,
				target_name: target.name,
				status: status,
				started_at: new Date(Date.now() - i * 3600000 - Math.random() * 3600000).toISOString(),
				completed_at: new Date(Date.now() - i * 3600000).toISOString(),
				result: {
					collected_count: Math.floor(Math.random() * 50) + 10,
					new_count: Math.floor(Math.random() * 10),
					updated_count: Math.floor(Math.random() * 5),
					duration_seconds: Math.random() * 10 + 2
				},
				error_message: status === 'failed' ? '모바일 서버 연결 실패' : null
			});
		}

		return mockRuns;
	}

	const filteredRuns = $derived(() => {
		let result = runs;

		if (statusFilter !== 'all') {
			result = result.filter((r) => r.status === statusFilter);
		}

		if (targetFilter) {
			result = result.filter((r) => r.target_id === parseInt(targetFilter));
		}

		return result;
	});

	function getStatusBadgeClass(status) {
		switch (status) {
			case 'completed':
				return 'badge-success';
			case 'failed':
				return 'badge-error';
			case 'running':
				return 'badge-warning';
			default:
				return 'badge-ghost';
		}
	}

	function getStatusText(status) {
		switch (status) {
			case 'completed':
				return '완료';
			case 'failed':
				return '실패';
			case 'running':
				return '실행중';
			default:
				return status;
		}
	}

	onMount(() => {
		loadData();
	});
</script>

<div class="container mx-auto p-4">
	<div class="mb-6">
		<h1 class="text-2xl font-bold">실행 이력</h1>
		<p class="text-gray-600 mt-1">모바일 크롤링 실행 이력을 조회합니다.</p>
	</div>

	<!-- 필터 -->
	<div class="card bg-base-100 shadow mb-6">
		<div class="card-body">
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div class="form-control">
					<label class="label">
						<span class="label-text">상태</span>
					</label>
					<select bind:value={statusFilter} class="select select-bordered">
						<option value="all">전체</option>
						<option value="completed">완료</option>
						<option value="failed">실패</option>
					</select>
				</div>

				<div class="form-control">
					<label class="label">
						<span class="label-text">대상</span>
					</label>
					<select bind:value={targetFilter} class="select select-bordered">
						<option value={null}>전체</option>
						{#each targets as target}
							<option value={target.id}>{target.name}</option>
						{/each}
					</select>
				</div>
			</div>
		</div>
	</div>

	<!-- 로딩 -->
	{#if loading}
		<div class="text-center py-8">로딩 중...</div>
	{:else if error}
		<div class="alert alert-error">{error}</div>
	{:else}
		<!-- 이력 테이블 -->
		<div class="overflow-x-auto">
			<table class="table table-zebra">
				<thead>
					<tr>
						<th>ID</th>
						<th>대상</th>
						<th>상태</th>
						<th>실행 시각</th>
						<th>수집 건수</th>
						<th>소요 시간</th>
						<th>동작</th>
					</tr>
				</thead>
				<tbody>
					{#each filteredRuns() as run}
						<tr>
							<td>{run.id}</td>
							<td>
								<button
									class="link link-primary"
									onclick={() => goto(`/mobile/targets/${run.target_id}`)}
								>
									{run.target_name}
								</button>
							</td>
							<td>
								<div class="badge {getStatusBadgeClass(run.status)}">
									{getStatusText(run.status)}
								</div>
							</td>
							<td>{new Date(run.started_at).toLocaleString()}</td>
							<td>
								{#if run.status === 'completed'}
									<div class="text-sm">
										<div>총 {run.result.collected_count}건</div>
										<div class="text-xs text-gray-500">
											신규 {run.result.new_count} / 변경 {run.result.updated_count}
										</div>
									</div>
								{:else if run.error_message}
									<div class="text-sm text-error">{run.error_message}</div>
								{:else}
									-
								{/if}
							</td>
							<td>
								{#if run.result?.duration_seconds}
									{run.result.duration_seconds.toFixed(2)}초
								{:else}
									-
								{/if}
							</td>
							<td>
								<button
									class="btn btn-xs btn-ghost"
									onclick={() => goto(`/mobile/runs/${run.id}/items`)}
								>
									결과 보기
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>

			{#if filteredRuns().length === 0}
				<div class="text-center py-8 text-gray-500">실행 이력이 없습니다.</div>
			{/if}
		</div>
	{/if}
</div>
