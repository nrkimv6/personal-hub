<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	let targets = $state([]);
	let loading = $state(true);
	let error = $state(null);

	async function loadTargets() {
		try {
			loading = true;
			const response = await fetch('/api/v1/mobile/targets');
			if (!response.ok) throw new Error('대상 목록 조회 실패');
			targets = await response.json();
		} catch (err) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	async function deleteTarget(id) {
		if (!confirm('정말 삭제하시겠습니까?')) return;

		try {
			const response = await fetch(`/api/v1/mobile/targets/${id}`, {
				method: 'DELETE'
			});
			if (!response.ok) throw new Error('삭제 실패');
			await loadTargets();
		} catch (err) {
			alert(err.message);
		}
	}

	async function executeTarget(id) {
		if (!confirm('즉시 크롤링을 실행하시겠습니까?')) return;

		try {
			const response = await fetch(`/api/v1/mobile/targets/${id}/execute`, {
				method: 'POST'
			});
			if (!response.ok) throw new Error('실행 실패');
			const result = await response.json();

			if (result.success) {
				alert(
					`크롤링 완료!\n` +
					`수집: ${result.collected_count}건\n` +
					`신규: ${result.new_count}건\n` +
					`변경: ${result.updated_count}건\n` +
					`소요시간: ${result.duration_seconds.toFixed(2)}초`
				);
				await loadTargets();
			} else {
				alert(`실행 실패: ${result.error}`);
			}
		} catch (err) {
			alert(err.message);
		}
	}

	onMount(() => {
		loadTargets();
	});
</script>

<div class="container mx-auto p-4">
	<div class="flex justify-between items-center mb-6">
		<h1 class="text-2xl font-bold">모바일 크롤링 대상</h1>
		<button
			class="btn btn-primary"
			onclick={() => goto('/mobile/targets/new')}
		>
			+ 새 대상 추가
		</button>
	</div>

	{#if loading}
		<div class="text-center py-8">로딩 중...</div>
	{:else if error}
		<div class="alert alert-error">{error}</div>
	{:else if targets.length === 0}
		<div class="text-center py-8 text-gray-500">
			등록된 크롤링 대상이 없습니다.
		</div>
	{:else}
		<div class="grid gap-4">
			{#each targets as target}
				<div class="card bg-base-100 shadow-md">
					<div class="card-body">
						<div class="flex justify-between items-start">
							<div class="flex-1">
								<h2 class="card-title">
									{target.name}
									{#if !target.is_active}
										<span class="badge badge-ghost">비활성</span>
									{/if}
								</h2>
								<p class="text-sm text-gray-600 mt-1 break-all">{target.url}</p>
								<div class="flex gap-2 mt-2">
									<span class="badge badge-outline">{target.crawl_type}</span>
									<span class="badge badge-outline">
										생성: {new Date(target.created_at).toLocaleDateString()}
									</span>
								</div>
							</div>
							<div class="flex gap-2">
								<button
									class="btn btn-sm btn-primary"
									onclick={() => executeTarget(target.id)}
								>
									즉시 실행
								</button>
								<button
									class="btn btn-sm btn-ghost"
									onclick={() => goto(`/mobile/targets/${target.id}`)}
								>
									상세
								</button>
								<button
									class="btn btn-sm btn-ghost"
									onclick={() => goto(`/mobile/targets/${target.id}/edit`)}
								>
									수정
								</button>
								<button
									class="btn btn-sm btn-error btn-outline"
									onclick={() => deleteTarget(target.id)}
								>
									삭제
								</button>
							</div>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
