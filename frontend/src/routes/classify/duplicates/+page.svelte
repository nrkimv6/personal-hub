<script lang="ts">
	import { onMount } from 'svelte';

	interface DuplicateGroup {
		group_id: number;
		group_hash: string;
		member_count: number;
		status: string;
		kept_file_id: number | null;
	}

	interface DuplicateMember {
		file_id: number;
		file_path: string;
		file_size: number;
		resolution: string;
		quality_score: number;
		phash_distance: number;
		is_exact: boolean;
	}

	let groups: DuplicateGroup[] = [];
	let selectedGroup: any = null;
	let loading = true;
	let error: string | null = null;

	let filter = {
		status: 'pending', // pending/resolved/ignored/all
		skip: 0,
		limit: 50
	};

	async function loadGroups() {
		loading = true;
		error = null;
		try {
			const params = new URLSearchParams();
			params.set('skip', filter.skip.toString());
			params.set('limit', filter.limit.toString());
			if (filter.status !== 'all') {
				params.set('status', filter.status);
			}

			const res = await fetch(`/api/ic/duplicates?${params}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			groups = data.groups;
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	async function loadGroupDetail(groupId: number) {
		try {
			const res = await fetch(`/api/ic/duplicates/${groupId}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			selectedGroup = await res.json();
		} catch (err: any) {
			alert(`그룹 로드 실패: ${err.message}`);
		}
	}

	async function resolveGroup(groupId: number, keepFileId: number) {
		if (!confirm(`파일 ID ${keepFileId}를 보관하고 나머지를 휴지통으로 이동하시겠습니까?`)) {
			return;
		}

		try {
			const res = await fetch(`/api/ic/duplicates/${groupId}/resolve`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					keep_file_id: keepFileId,
					delete_others: true
				})
			});

			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();

			alert(`✅ 해결 완료!\n보관: ${result.kept_file_id}\n삭제: ${result.deleted_count}개`);

			// 목록 갱신
			selectedGroup = null;
			await loadGroups();
		} catch (err: any) {
			alert(`해결 실패: ${err.message}`);
		}
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}

	onMount(() => {
		loadGroups();
	});
</script>

<svelte:head>
	<title>중복 이미지 관리</title>
</svelte:head>

<div class="max-w-7xl mx-auto">
	<h1 class="text-3xl font-bold text-gray-900 mb-2">🔍 중복 이미지 관리</h1>
	<p class="text-gray-600 mb-6">pHash 기반 중복 이미지 탐지 및 정리</p>

	<!-- 필터 -->
	<div class="bg-white rounded-lg shadow mb-6 p-4">
		<div class="flex items-center gap-4">
			<div class="flex items-center gap-2">
				<label class="text-sm font-medium text-gray-700">상태:</label>
				<select
					bind:value={filter.status}
					on:change={loadGroups}
					class="px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-blue-500"
				>
					<option value="all">전체</option>
					<option value="pending">미해결</option>
					<option value="resolved">해결됨</option>
					<option value="ignored">무시됨</option>
				</select>
			</div>

			<button
				on:click={loadGroups}
				class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors text-sm"
			>
				🔄 새로고침
			</button>

			<div class="ml-auto text-sm text-gray-600">
				총 {groups.length}개 그룹
			</div>
		</div>
	</div>

	{#if loading}
		<div class="bg-white rounded-lg shadow p-8 text-center">
			<div class="animate-spin text-4xl mb-4">⏳</div>
			<p class="text-gray-600">중복 그룹 로딩 중...</p>
		</div>
	{:else if error}
		<div class="bg-red-50 border border-red-200 rounded-lg p-6">
			<h3 class="text-red-800 font-semibold mb-2">⚠️ 오류 발생</h3>
			<p class="text-red-600">{error}</p>
		</div>
	{:else if groups.length === 0}
		<div class="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
			<div class="text-6xl mb-4">🎉</div>
			<p class="text-gray-700 font-medium">중복 이미지가 없습니다!</p>
			<p class="text-gray-500 text-sm mt-2">또는 pHash 계산이 완료되지 않았을 수 있습니다.</p>
		</div>
	{:else}
		<!-- 중복 그룹 목록 -->
		<div class="bg-white rounded-lg shadow">
			<div class="overflow-x-auto">
				<table class="min-w-full divide-y divide-gray-200">
					<thead class="bg-gray-50">
						<tr>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">그룹 ID</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">멤버 수</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">대표 해시</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">작업</th>
						</tr>
					</thead>
					<tbody class="bg-white divide-y divide-gray-200">
						{#each groups as group}
							<tr class="hover:bg-gray-50">
								<td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">
									#{group.group_id}
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
									{group.member_count}개
								</td>
								<td class="px-6 py-4 whitespace-nowrap">
									<span class="px-2 py-1 text-xs rounded-full {group.status === 'pending'
										? 'bg-yellow-100 text-yellow-800'
										: group.status === 'resolved'
										? 'bg-green-100 text-green-800'
										: 'bg-gray-100 text-gray-800'}">
										{group.status === 'pending' ? '미해결' : group.status === 'resolved' ? '해결됨' : '무시됨'}
									</span>
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-xs font-mono text-gray-500">
									{group.group_hash.substring(0, 16)}...
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<button
										on:click={() => loadGroupDetail(group.group_id)}
										class="text-blue-600 hover:text-blue-800 font-medium"
									>
										상세 보기 →
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<!-- 상세 모달 -->
	{#if selectedGroup}
		<div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
			<div class="bg-white rounded-lg shadow-xl max-w-6xl w-full max-h-[90vh] overflow-y-auto">
				<div class="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between">
					<div>
						<h2 class="text-2xl font-bold text-gray-900">
							중복 그룹 #{selectedGroup.group_id}
						</h2>
						<p class="text-sm text-gray-600 mt-1">
							{selectedGroup.member_count}개 이미지 — 품질 점수 높은 순
						</p>
					</div>
					<button
						on:click={() => (selectedGroup = null)}
						class="text-gray-400 hover:text-gray-600 text-2xl"
					>
						✕
					</button>
				</div>

				<div class="p-6">
					<!-- 멤버 비교 그리드 -->
					<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
						{#each selectedGroup.members as member}
							<div class="border rounded-lg overflow-hidden hover:shadow-lg transition-shadow">
								<!-- 썸네일 -->
								<div class="bg-gray-100 aspect-square relative">
									<img
										src={getThumbnailUrl(member.file_id)}
										alt="파일 {member.file_id}"
										class="w-full h-full object-contain"
										on:error={(e) => {
											e.currentTarget.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="%23f3f4f6"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="%239ca3af" font-family="sans-serif">No Image</text></svg>';
										}}
									/>
									{#if member.is_exact}
										<div class="absolute top-2 right-2 bg-red-500 text-white text-xs px-2 py-1 rounded-full font-bold">
											SHA256 일치
										</div>
									{/if}
								</div>

								<!-- 정보 -->
								<div class="p-4 space-y-2">
									<div class="flex justify-between items-start">
										<div class="text-xs text-gray-500 break-all flex-1 mr-2">
											{member.file_path.split('\\').pop()}
										</div>
										<div class="text-xs font-mono bg-blue-50 text-blue-700 px-2 py-1 rounded">
											ID: {member.file_id}
										</div>
									</div>

									<div class="grid grid-cols-2 gap-2 text-xs">
										<div>
											<span class="text-gray-500">크기:</span>
											<span class="font-medium">{formatFileSize(member.file_size)}</span>
										</div>
										<div>
											<span class="text-gray-500">해상도:</span>
											<span class="font-medium">{member.resolution}</span>
										</div>
										<div>
											<span class="text-gray-500">품질 점수:</span>
											<span class="font-medium">{member.quality_score.toFixed(0)}</span>
										</div>
										<div>
											<span class="text-gray-500">pHash 거리:</span>
											<span class="font-medium">{member.phash_distance}</span>
										</div>
									</div>

									{#if selectedGroup.status === 'pending'}
										<button
											on:click={() => resolveGroup(selectedGroup.group_id, member.file_id)}
											class="w-full mt-3 px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 transition-colors text-sm font-medium"
										>
											✅ 이 파일 보관 (나머지 삭제)
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>

					{#if selectedGroup.status === 'resolved'}
						<div class="mt-6 bg-green-50 border border-green-200 rounded-lg p-4">
							<p class="text-green-800 text-sm">
								✅ 이 그룹은 이미 해결되었습니다. (보관: 파일 ID {selectedGroup.members.find((m: any) => m.file_id === selectedGroup.kept_file_id)?.file_id || '?'})
							</p>
						</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	/* 모달 스크롤 스타일 */
	:global(body) {
		overflow: auto;
	}
</style>
