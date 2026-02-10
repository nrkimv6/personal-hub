<script>
	import { onMount } from "svelte";
	import { page } from "$app/stores";

	let items = $state([]);
	let loading = $state(true);
	let error = $state(null);

	// 필터
	let targetFilter = $state(null);
	let showOnlyChanged = $state(false);
	let targets = $state([]);

	// 페이지네이션
	let currentPage = $state(1);
	let itemsPerPage = 20;

	// 선택된 아이템 (모달용)
	let selectedItem = $state(null);

	async function loadData() {
		try {
			loading = true;

			// 대상 목록 로드
			const targetsRes = await fetch("/api/v1/mobile/targets");
			if (targetsRes.ok) {
				targets = await targetsRes.json();
			}

			// Mock 아이템 데이터 생성
			items = generateMockItems();
		} catch (err) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function generateMockItems() {
		const mockItems = [];

		for (let i = 0; i < 50; i++) {
			const target = targets[i % Math.max(targets.length, 1)] || {
				id: 1,
				name: "Mock 대상",
			};
			const isChanged = Math.random() > 0.7;

			mockItems.push({
				id: i + 1,
				target_id: target.id,
				target_name: target.name,
				title: `Mock 아이템 ${i + 1}`,
				item_url: `https://example.com/items/${i + 1}`,
				image_url: `https://via.placeholder.com/300x200?text=Item+${i + 1}`,
				is_changed: isChanged,
				attributes: {
					price: `${Math.floor(Math.random() * 100 + 10) * 1000}원`,
					status: Math.random() > 0.5 ? "재고 있음" : "품절",
					date: new Date(Date.now() - i * 86400000)
						.toISOString()
						.split("T")[0],
				},
				first_seen_at: new Date(
					Date.now() - i * 86400000 - 7 * 86400000,
				).toISOString(),
				last_seen_at: new Date(Date.now() - i * 86400000).toISOString(),
			});
		}

		return mockItems;
	}

	const filteredItems = $derived(() => {
		let result = items;

		if (targetFilter) {
			result = result.filter(
				(item) => item.target_id === parseInt(targetFilter),
			);
		}

		if (showOnlyChanged) {
			result = result.filter((item) => item.is_changed);
		}

		return result;
	});

	const paginatedItems = $derived(() => {
		const start = (currentPage - 1) * itemsPerPage;
		const end = start + itemsPerPage;
		return filteredItems().slice(start, end);
	});

	const totalPages = $derived(
		Math.ceil(filteredItems().length / itemsPerPage),
	);

	function openItemDetail(item) {
		selectedItem = item;
	}

	function closeItemDetail() {
		selectedItem = null;
	}

	onMount(() => {
		loadData();
	});
</script>

<div class="container mx-auto p-4">
	<div class="mb-6">
		<h1 class="text-2xl font-bold">수집 아이템 목록</h1>
		<p class="text-gray-600 mt-1">
			모든 대상에서 수집된 아이템을 조회합니다.
		</p>
	</div>

	<!-- 필터 -->
	<div class="card bg-base-100 shadow mb-6">
		<div class="card-body">
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div class="form-control">
					<label class="label">
						<span class="label-text">대상</span>
					</label>
					<select
						bind:value={targetFilter}
						class="select select-bordered"
					>
						<option value={null}>전체</option>
						{#each targets as target}
							<option value={target.id}>{target.name}</option>
						{/each}
					</select>
				</div>

				<div class="form-control">
					<label class="label cursor-pointer justify-start gap-2">
						<input
							type="checkbox"
							bind:checked={showOnlyChanged}
							class="checkbox"
						/>
						<span class="label-text">변경된 아이템만 보기</span>
					</label>
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
		<!-- 아이템 그리드 -->
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
			{#each paginatedItems() as item}
				<div
					class="card bg-base-100 shadow hover:shadow-lg transition-shadow cursor-pointer"
				>
					<button
						onclick={() => openItemDetail(item)}
						class="text-left"
					>
						{#if item.image_url}
							<figure>
								<img
									src={item.image_url}
									alt={item.title}
									class="w-full h-48 object-cover"
								/>
							</figure>
						{/if}
						<div class="card-body">
							<h3 class="card-title text-base">
								{item.title}
								{#if item.is_changed}
									<span class="badge badge-warning badge-sm"
										>변경됨</span
									>
								{/if}
							</h3>

							<div class="text-sm space-y-1">
								{#if item.attributes.price}
									<div>
										<strong>가격:</strong>
										{item.attributes.price}
									</div>
								{/if}
								{#if item.attributes.status}
									<div>
										<strong>상태:</strong>
										{item.attributes.status}
									</div>
								{/if}
							</div>

							<div class="text-xs text-gray-500 mt-2">
								최종: {new Date(
									item.last_seen_at,
								).toLocaleString()}
							</div>
						</div>
					</button>
				</div>
			{/each}
		</div>

		{#if filteredItems().length === 0}
			<div class="text-center py-8 text-gray-500">아이템이 없습니다.</div>
		{/if}

		<!-- 페이지네이션 -->
		{#if totalPages > 1}
			<div class="flex justify-center">
				<div class="join">
					<button
						class="join-item btn"
						disabled={currentPage === 1}
						onclick={() => (currentPage = currentPage - 1)}
					>
						«
					</button>
					{#each Array.from({ length: Math.min(10, totalPages) }, (_, i) => i + 1) as page}
						<button
							class="join-item btn"
							class:btn-active={currentPage === page}
							onclick={() => (currentPage = page)}
						>
							{page}
						</button>
					{/each}
					<button
						class="join-item btn"
						disabled={currentPage === totalPages}
						onclick={() => (currentPage = currentPage + 1)}
					>
						»
					</button>
				</div>
			</div>
		{/if}
	{/if}
</div>

<!-- 아이템 상세 모달 (7-8) -->
{#if selectedItem}
	<div class="modal modal-open">
		<div class="modal-box w-11/12 max-w-3xl">
			<h3 class="font-bold text-lg mb-4 break-words">
				{selectedItem.title}
			</h3>

			{#if selectedItem.image_url}
				<img
					src={selectedItem.image_url}
					alt={selectedItem.title}
					class="w-full rounded-lg mb-4"
				/>
			{/if}

			<div class="space-y-4">
				<!-- 기본 정보 -->
				<div>
					<h4 class="font-semibold mb-2">기본 정보</h4>
					<div class="space-y-1 text-sm">
						<div>
							<strong>대상:</strong>
							{selectedItem.target_name}
						</div>
						{#if selectedItem.item_url}
							<div>
								<strong>URL:</strong>
								<a
									href={selectedItem.item_url}
									target="_blank"
									class="link link-primary break-all"
								>
									{selectedItem.item_url}
								</a>
							</div>
						{/if}
						<div>
							<strong>최초 발견:</strong>
							{new Date(
								selectedItem.first_seen_at,
							).toLocaleString()}
						</div>
						<div>
							<strong>최종 확인:</strong>
							{new Date(
								selectedItem.last_seen_at,
							).toLocaleString()}
						</div>
					</div>
				</div>

				<!-- 속성 -->
				<div>
					<h4 class="font-semibold mb-2">속성</h4>
					<div class="bg-base-200 p-3 rounded text-sm">
						{#each Object.entries(selectedItem.attributes) as [key, value]}
							<div
								class="flex flex-col sm:flex-row sm:justify-between py-2 border-b last:border-0 border-base-300 gap-1"
							>
								<span class="font-medium shrink-0">{key}:</span>
								<span
									class="break-all sm:text-right text-gray-600"
									>{value}</span
								>
							</div>
						{/each}
					</div>
				</div>

				<!-- 변경 이력 (Mock) -->
				<div>
					<h4 class="font-semibold mb-2">변경 이력</h4>
					<ul class="timeline timeline-vertical timeline-compact">
						<li>
							<div class="timeline-middle">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-5 h-5 text-primary"
								>
									<path
										fill-rule="evenodd"
										d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
										clip-rule="evenodd"
									/>
								</svg>
							</div>
							<div class="timeline-end timeline-box">
								<div class="font-semibold">최종 확인</div>
								<div class="text-xs">
									{new Date(
										selectedItem.last_seen_at,
									).toLocaleString()}
								</div>
								<div class="text-sm mt-1">변경사항 없음</div>
							</div>
							<hr />
						</li>
						<li>
							<hr />
							<div class="timeline-middle">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-5 h-5"
								>
									<path
										fill-rule="evenodd"
										d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z"
										clip-rule="evenodd"
									/>
								</svg>
							</div>
							<div class="timeline-end timeline-box">
								<div class="font-semibold">최초 발견</div>
								<div class="text-xs">
									{new Date(
										selectedItem.first_seen_at,
									).toLocaleString()}
								</div>
							</div>
						</li>
					</ul>
				</div>
			</div>

			<div class="modal-action">
				<button class="btn" onclick={closeItemDetail}>닫기</button>
				{#if selectedItem.item_url}
					<a
						href={selectedItem.item_url}
						target="_blank"
						class="btn btn-primary"
					>
						원본 페이지 열기
					</a>
				{/if}
			</div>
		</div>
		<form method="dialog" class="modal-backdrop">
			<button onclick={closeItemDetail}>close</button>
		</form>
	</div>
{/if}
