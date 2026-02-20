<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { Copy, Wand2, Check, Trash2, SkipForward, Crown, PartyPopper, Square } from 'lucide-svelte';

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

	interface GroupDetail extends DuplicateGroup {
		members: DuplicateMember[];
	}

	let groups: DuplicateGroup[] = $state([]);
	let groupDetails = $state<Record<number, GroupDetail>>({});
	let loading = $state(true);
	let error = $state<string | null>(null);
	let filter = { status: 'pending', skip: 0, limit: 50 };

	// 각 그룹에서 선택된 keep 파일 ID
	let selections = $state<Record<number, number | null>>({});

	let filterStatus = $state('unresolved');
	let detectRunning = $state(false);
	let detectStatusPoller: ReturnType<typeof setInterval> | null = null;

	async function checkDetectStatus() {
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/detect/status');
			if (!res.ok) return;
			const data = await res.json();
			detectRunning = data.is_running ?? false;
		} catch {
			// ignore
		}
	}

	async function stopDetect() {
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/detect/stop', { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			detectRunning = false;
			alert('중복탐지가 중지되었습니다.');
			await loadGroups();
		} catch (err: any) {
			alert(`중지 실패: ${err.message}`);
		}
	}

	const filteredGroups = $derived(
		filterStatus === 'all'
			? groups
			: filterStatus === 'unresolved'
				? groups.filter((g) => g.status === 'pending')
				: groups.filter((g) => g.status === 'resolved')
	);

	const resolvedCount = $derived(groups.filter((g) => g.status === 'resolved').length);
	const allResolved = $derived(groups.length > 0 && resolvedCount === groups.length);

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

			const res = await fetchWithTimeout(`/api/ic/duplicates?${params}`);
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
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const detail = await res.json();
			groupDetails = { ...groupDetails, [groupId]: detail };
		} catch (err: any) {
			alert(`그룹 로드 실패: ${err.message}`);
		}
	}

	async function resolveGroup(groupId: number, keepFileId: number) {
		if (!confirm(`파일 ID ${keepFileId}를 보관하고 나머지를 휴지통으로 이동하시겠습니까?`)) {
			return;
		}

		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}/resolve`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					keep_file_id: keepFileId,
					delete_others: true
				})
			});

			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();

			alert(`해결 완료!\n보관: ${result.kept_file_id}\n삭제: ${result.deleted_count}개`);

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

	function getBestMember(members: DuplicateMember[]): number {
		return members.reduce((best, m) => (m.quality_score > best.quality_score ? m : best), members[0])
			?.file_id;
	}

	function getFileName(path: string): string {
		return path.split('\\').pop() || path.split('/').pop() || path;
	}

	async function toggleGroupDetail(groupId: number) {
		if (groupDetails[groupId]) {
			const updated = { ...groupDetails };
			delete updated[groupId];
			groupDetails = updated;
		} else {
			await loadGroupDetail(groupId);
		}
	}

	onMount(() => {
		loadGroups();
		checkDetectStatus();
		detectStatusPoller = setInterval(checkDetectStatus, 3000);
		return () => {
			if (detectStatusPoller) clearInterval(detectStatusPoller);
		};
	});
</script>

<!-- 헤더 -->
<div class="mb-4">
	<div class="flex items-center gap-2">
		<Copy class="size-5 text-primary" />
		<h2 class="text-xl font-bold tracking-tight">중복 이미지</h2>
	</div>
	<p class="mt-1 text-sm text-muted-foreground">pHash 기반 중복 이미지 탐지 및 정리</p>
</div>

<!-- 컨트롤 바 -->
<div class="rounded-xl border bg-card p-4 mb-6">
	<div class="flex items-center gap-4 flex-wrap">
		<!-- 통계 -->
		<div class="flex items-center gap-2 text-sm">
			<span class="font-medium">{groups.length}개 그룹</span>
			<span class="text-muted-foreground">|</span>
			<span class="text-muted-foreground">{resolvedCount}개 해결됨</span>
		</div>

		<!-- 필터 버튼 그룹 -->
		<div class="flex items-center rounded-lg border bg-muted/40 p-0.5 gap-0.5">
			{#each [['all', '전체'], ['unresolved', '미해결'], ['resolved', '해결됨']] as [val, label]}
				<button
					class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {filterStatus === val
						? 'bg-background text-foreground shadow-sm'
						: 'text-muted-foreground hover:text-foreground'}"
					onclick={() => (filterStatus = val)}
				>
					{label}
				</button>
			{/each}
		</div>

		<!-- 중지 버튼 (탐지 실행 중일 때만 표시) -->
		{#if detectRunning}
			<button
				class="flex items-center gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
				onclick={stopDetect}
			>
				<Square class="size-3.5" />
				탐지 중지
			</button>
		{/if}

		<!-- 새로고침 -->
		<button
			class="ml-auto flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-accent transition-colors"
			onclick={loadGroups}
		>
			<Wand2 class="size-3.5" />
			새로고침
		</button>
	</div>
</div>

<!-- 로딩/에러 -->
{#if loading}
	<div class="rounded-xl border bg-card p-12 text-center">
		<div class="text-muted-foreground text-sm animate-pulse">중복 그룹 로딩 중...</div>
	</div>
{:else if error}
	<div class="rounded-xl border border-destructive/50 bg-destructive/5 p-6">
		<p class="text-destructive text-sm font-medium">오류: {error}</p>
	</div>
{:else if allResolved}
	<div class="rounded-xl border bg-card p-12 text-center">
		<PartyPopper class="size-12 text-primary mx-auto mb-3" />
		<p class="font-semibold text-lg">모든 중복 이미지 처리 완료!</p>
		<p class="text-muted-foreground text-sm mt-1">모든 중복 그룹이 처리되었습니다.</p>
	</div>
{:else if filteredGroups.length === 0}
	<div class="rounded-xl border bg-card p-12 text-center">
		<p class="text-muted-foreground text-sm">표시할 그룹이 없습니다.</p>
	</div>
{:else}
	<!-- 그룹 카드 리스트 -->
	<div class="space-y-4">
		{#each filteredGroups as group (group.group_id)}
			{@const detail = groupDetails[group.group_id]}
			<div class="rounded-xl border bg-card overflow-hidden">
				<!-- 카드 헤더 -->
				<div class="flex items-center justify-between px-4 py-3 border-b bg-muted/20">
					<div class="flex items-center gap-3">
						<span class="font-mono text-sm font-semibold">Group #{group.group_id}</span>
						<span
							class="text-[11px] px-2 py-0.5 rounded-full font-medium {group.status === 'pending'
								? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
								: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'}"
						>
							{group.status === 'pending' ? '대기 중' : '해결됨'}
						</span>
						<span class="text-xs text-muted-foreground">{group.member_count}이미지</span>
					</div>
					<div class="flex items-center gap-2">
						<button
							class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent transition-colors"
							onclick={() => toggleGroupDetail(group.group_id)}
						>
							<SkipForward class="size-3.5" />
							{detail ? '접기' : '펼치기'}
						</button>
						{#if group.status === 'pending' && detail}
							{@const keepId = selections[group.group_id] ?? getBestMember(detail.members)}
							<button
								class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
								onclick={() => resolveGroup(group.group_id, keepId)}
							>
								<Check class="size-3.5" />
								보관 확정
							</button>
						{/if}
					</div>
				</div>

				<!-- 카드 바디 (확장 시) -->
				{#if detail}
					<div class="p-4">
						<div class="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
							{#each detail.members as member (member.file_id)}
								{@const isBest = member.file_id === getBestMember(detail.members)}
								{@const isSelected = selections[group.group_id] === member.file_id}
								{@const isTrashed =
									selections[group.group_id] !== undefined &&
									selections[group.group_id] !== member.file_id}

								<div
									class="rounded-lg border overflow-hidden transition-all {isSelected
										? 'border-green-400 ring-2 ring-green-400/30'
										: isTrashed
											? 'border-destructive/40 opacity-60'
											: 'border-border hover:border-primary/40'}"
								>
									<!-- 썸네일 -->
									<div class="relative aspect-square bg-muted">
										<img
											src={getThumbnailUrl(member.file_id)}
											alt="file {member.file_id}"
											class="w-full h-full object-cover"
											loading="lazy"
											decoding="async"
											onerror={(e) => {
												(e.currentTarget as HTMLImageElement).src =
													'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="%23f3f4f6"/><text x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%239ca3af" font-family="sans-serif">No Image</text></svg>';
											}}
										/>
										{#if isBest}
											<div
												class="absolute top-1.5 left-1.5 rounded-full bg-yellow-400 text-yellow-900 p-1 shadow"
											>
												<Crown class="size-3" />
											</div>
										{/if}
										{#if member.is_exact}
											<div
												class="absolute top-1.5 right-1.5 rounded-full bg-destructive/90 text-destructive-foreground px-1.5 py-0.5 text-[10px] font-bold"
											>
												SHA256
											</div>
										{/if}
									</div>

									<!-- 정보 -->
									<div class="p-2 space-y-1.5 bg-card">
										<p class="text-[11px] font-mono truncate text-muted-foreground" title={member.file_path}>
											{getFileName(member.file_path)}
										</p>

										<!-- 품질 바 -->
										<div class="h-1 bg-muted rounded-full overflow-hidden">
											<div
												class="h-full bg-primary rounded-full"
												style="width: {Math.min(member.quality_score, 100)}%"
											></div>
										</div>

										<div class="flex items-center justify-between text-[10px] text-muted-foreground">
											<span>{formatFileSize(member.file_size)}</span>
											<span>{member.resolution}</span>
										</div>

										<!-- Keep/Trash 토글 -->
										{#if group.status === 'pending'}
											<div class="flex gap-1 pt-0.5">
												<button
													class="flex-1 flex items-center justify-center gap-1 rounded py-1 text-[11px] font-medium transition-colors {isSelected
														? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
														: 'text-muted-foreground hover:bg-muted'}"
													onclick={() => {
														selections = { ...selections, [group.group_id]: member.file_id };
													}}
												>
													<Check class="size-3" />
													보관
												</button>
												<button
													class="flex-1 flex items-center justify-center gap-1 rounded py-1 text-[11px] font-medium transition-colors {isTrashed
														? 'bg-destructive/10 text-destructive'
														: 'text-muted-foreground hover:bg-muted'}"
													onclick={() => {
														// 이 멤버를 trash로 표시 = 다른 멤버를 자동 keep
														const others = detail.members.filter(
															(m) => m.file_id !== member.file_id
														);
														if (others.length === 1) {
															selections = { ...selections, [group.group_id]: others[0].file_id };
														}
													}}
												>
													<Trash2 class="size-3" />
													버리기
												</button>
											</div>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					</div>

					<!-- 카드 푸터 (resolved) -->
					{#if group.status === 'resolved'}
						<div class="px-4 py-3 border-t bg-emerald-500/5 dark:bg-emerald-900/10">
							<p class="text-xs text-green-700 dark:text-green-400 flex items-center gap-1.5">
								<Check class="size-3.5" />
								해결 완료: 파일 ID {group.kept_file_id} 보관
							</p>
						</div>
					{/if}
				{/if}
			</div>
		{/each}
	</div>
{/if}
