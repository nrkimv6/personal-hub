<script>
	import { page } from "$app/stores";
	import { onMount } from "svelte";
	import { goto } from "$app/navigation";
  import { fetchWithTimeout } from '$lib/api/client';

	const targetId = $derived($page.params.id);

	let target = $state(null);
	let stats = $state(null);
	let items = $state([]);
	let loading = $state(true);
	let error = $state(null);

	async function loadData() {
		try {
			loading = true;

			// 대상 정보
			const targetRes = await fetchWithTimeout(`/api/v1/mobile/targets/${targetId}`);
			if (!targetRes.ok) throw new Error("대상 조회 실패");
			target = await targetRes.json();

			// 통계
			const statsRes = await fetchWithTimeout(
				`/api/v1/mobile/targets/${targetId}/stats`,
			);
			if (statsRes.ok) {
				stats = await statsRes.json();
			}

			// 최근 아이템
			const itemsRes = await fetchWithTimeout(
				`/api/v1/mobile/targets/${targetId}/items?limit=20`,
			);
			if (itemsRes.ok) {
				items = await itemsRes.json();
			}
		} catch (err) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	async function executeTarget() {
		if (!confirm("즉시 크롤링을 실행하시겠습니까?")) return;

		try {
			const response = await fetchWithTimeout(
				`/api/v1/mobile/targets/${targetId}/execute`,
				{
					method: "POST",
				},
			);
			if (!response.ok) throw new Error("실행 실패");
			const result = await response.json();

			if (result.success) {
				alert(
					`크롤링 완료!\n` +
						`수집: ${result.collected_count}건\n` +
						`신규: ${result.new_count}건\n` +
						`변경: ${result.updated_count}건\n` +
						`소요시간: ${result.duration_seconds.toFixed(2)}초`,
				);
				await loadData();
			} else {
				alert(`실행 실패: ${result.error}`);
			}
		} catch (err) {
			alert(err.message);
		}
	}

	onMount(() => {
		loadData();
	});
</script>

<div class="container mx-auto p-4">
	{#if loading}
		<div class="text-center py-8">로딩 중...</div>
	{:else if error}
		<div class="alert alert-error">{error}</div>
	{:else if target}
		<div class="mb-6">
			<div
				class="flex flex-col sm:flex-row justify-between items-start gap-4"
			>
				<div class="w-full min-w-0">
					<h1 class="text-2xl font-bold break-words">
						{target.name}
					</h1>
					<p class="text-gray-600 mt-1 break-all">{target.url}</p>
				</div>
				<div class="flex gap-2 flex-wrap w-full sm:w-auto mt-4 sm:mt-0">
					<button
						class="btn btn-primary flex-auto sm:flex-none min-w-[6rem]"
						onclick={executeTarget}
					>
						즉시 실행
					</button>
					<button
						class="btn btn-secondary flex-auto sm:flex-none min-w-[4rem]"
						onclick={() =>
							goto(`/mobile/targets/${targetId}/schedule`)}
					>
						스케줄
					</button>
					<button
						class="btn btn-ghost flex-auto sm:flex-none min-w-[3rem]"
						onclick={() => goto(`/mobile/targets/${targetId}/edit`)}
					>
						수정
					</button>
					<button
						class="btn btn-ghost flex-auto sm:flex-none min-w-[3rem]"
						onclick={() => goto("/mobile/targets")}
					>
						목록
					</button>
				</div>
			</div>
		</div>

		{#if stats}
			<div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
				<div class="stat bg-base-100 shadow">
					<div class="stat-title">전체 아이템</div>
					<div class="stat-value text-primary">
						{stats.total_items}
					</div>
				</div>
				<div class="stat bg-base-100 shadow">
					<div class="stat-title">신규 아이템</div>
					<div class="stat-value text-success">
						{stats.new_items_count}
					</div>
				</div>
				<div class="stat bg-base-100 shadow">
					<div class="stat-title">변경 아이템</div>
					<div class="stat-value text-warning">
						{stats.changed_items_count}
					</div>
				</div>
				<div class="stat bg-base-100 shadow">
					<div class="stat-title">최근 실행</div>
					<div class="stat-value text-sm">
						{stats.latest_run_at
							? new Date(stats.latest_run_at).toLocaleString()
							: "N/A"}
					</div>
				</div>
			</div>
		{/if}

		<h2 class="text-xl font-bold mb-4">최근 수집 아이템</h2>
		{#if items.length === 0}
			<div class="text-center py-8 text-gray-500">
				아직 수집된 아이템이 없습니다.
			</div>
		{:else}
			<div class="grid gap-4">
				{#each items as item}
					<div class="card bg-base-100 shadow">
						<div class="card-body">
							<h3 class="card-title text-base">
								{item.title}
								{#if item.is_changed}
									<span class="badge badge-warning"
										>변경됨</span
									>
								{/if}
							</h3>
							{#if item.item_url}
								<a
									href={item.item_url}
									target="_blank"
									class="text-sm text-blue-600 hover:underline break-all"
								>
									{item.item_url}
								</a>
							{/if}
							<div class="text-sm text-gray-500">
								최초: {new Date(
									item.first_seen_at,
								).toLocaleString()} | 최종: {new Date(
									item.last_seen_at,
								).toLocaleString()}
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>
