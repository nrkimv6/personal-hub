<script lang="ts">
	/**
	 * 이벤트/팝업 출처 목록 컴포넌트
	 *
	 * 다중 출처를 표시하고 관리하는 UI
	 */
	import type { EntitySource } from '$lib/types';
	import { entitySourceApi } from '$lib/api';

	interface Props {
		entityType: 'events' | 'popups';
		entityId: number;
		isAdmin?: boolean;
	}

	let { entityType, entityId, isAdmin = false }: Props = $props();

	let sources: EntitySource[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let expanded = $state(false);

	// 출처 목록 로드
	async function loadSources() {
		loading = true;
		error = null;
		try {
			const result = await entitySourceApi.list(entityType, entityId);
			sources = result.items;
		} catch (e) {
			error = e instanceof Error ? e.message : '출처 로드 실패';
		} finally {
			loading = false;
		}
	}

	// 초기 로드
	$effect(() => {
		loadSources();
	});

	// 대표 출처 설정
	async function handleSetPrimary(sourceId: number) {
		try {
			await entitySourceApi.setPrimary(entityType, entityId, sourceId);
			await loadSources();
		} catch (e) {
			alert(e instanceof Error ? e.message : '대표 출처 설정 실패');
		}
	}

	// 출처 삭제
	async function handleRemove(sourceId: number) {
		if (!confirm('이 출처를 삭제하시겠습니까?')) return;
		try {
			await entitySourceApi.remove(entityType, entityId, sourceId);
			await loadSources();
		} catch (e) {
			alert(e instanceof Error ? e.message : '출처 삭제 실패');
		}
	}

	// 출처 유형 라벨
	function getSourceTypeLabel(type: string): string {
		switch (type) {
			case 'instagram': return 'Instagram';
			case 'web': return '웹';
			case 'manual': return '수동';
			default: return type;
		}
	}

	// 출처 유형 아이콘
	function getSourceTypeIcon(type: string): string {
		switch (type) {
			case 'instagram': return '📷';
			case 'web': return '🌐';
			case 'manual': return '✏️';
			default: return '📄';
		}
	}

	// 출처 유형별 색상
	function getSourceTypeColor(type: string): string {
		switch (type) {
			case 'instagram': return 'bg-pink-100 text-pink-700';
			case 'web': return 'bg-blue-100 text-blue-700';
			case 'manual': return 'bg-gray-100 text-gray-700';
			default: return 'bg-gray-100 text-gray-600';
		}
	}

	// 축약된 URL
	function truncateUrl(url: string | null, maxLength: number = 30): string {
		if (!url) return '-';
		if (url.length <= maxLength) return url;
		return url.substring(0, maxLength) + '...';
	}
</script>

{#if loading}
	<div class="text-sm text-gray-400 py-2">출처 로드 중...</div>
{:else if error}
	<div class="text-sm text-red-500 py-2">{error}</div>
{:else if sources.length === 0}
	<div class="text-sm text-gray-400 py-2">출처 정보 없음</div>
{:else}
	<div class="border-t border-gray-100 pt-3 mt-3">
		<!-- 헤더 -->
		<button
			class="w-full flex items-center justify-between text-left"
			onclick={() => expanded = !expanded}
		>
			<div class="flex items-center gap-2">
				<span class="text-sm font-medium text-gray-700">출처</span>
				<span class="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded-full">
					{sources.length}개
				</span>
			</div>
			<span class="text-gray-400 text-xs">
				{expanded ? '▲' : '▼'}
			</span>
		</button>

		<!-- 축소 시: 대표 출처만 표시 -->
		{#if !expanded}
			{@const primary = sources.find(s => s.is_primary) || sources[0]}
			{#if primary}
				<div class="mt-2 flex items-center gap-2 text-sm">
					<span class={`text-xs px-1.5 py-0.5 rounded ${getSourceTypeColor(primary.source_type)}`}>
						{getSourceTypeIcon(primary.source_type)} {getSourceTypeLabel(primary.source_type)}
					</span>
					{#if primary.source_account}
						<span class="text-gray-600">@{primary.source_account}</span>
					{:else if primary.source_url}
						<a
							href={primary.source_url}
							target="_blank"
							rel="noopener"
							class="text-blue-500 hover:underline truncate max-w-[200px]"
						>
							{truncateUrl(primary.source_url)}
						</a>
					{/if}
					{#if sources.length > 1}
						<span class="text-xs text-gray-400">+{sources.length - 1}</span>
					{/if}
				</div>
			{/if}
		{/if}

		<!-- 확장 시: 모든 출처 표시 -->
		{#if expanded}
			<div class="mt-2 space-y-2">
				{#each sources as source (source.id)}
					<div class="flex items-start justify-between gap-2 p-2 bg-gray-50 rounded text-sm">
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2">
								<span class={`text-xs px-1.5 py-0.5 rounded ${getSourceTypeColor(source.source_type)}`}>
									{getSourceTypeIcon(source.source_type)}
								</span>
								{#if source.is_primary}
									<span class="text-xs px-1.5 py-0.5 bg-yellow-100 text-yellow-700 rounded">
										대표
									</span>
								{/if}
								<span class="text-xs text-gray-400">
									우선순위: {source.priority}
								</span>
							</div>
							<div class="mt-1">
								{#if source.source_account}
									<span class="text-gray-700">@{source.source_account}</span>
								{/if}
								{#if source.source_url}
									<a
										href={source.source_url}
										target="_blank"
										rel="noopener"
										class="text-blue-500 hover:underline block truncate"
									>
										{source.source_url}
									</a>
								{/if}
							</div>
							{#if source.contributed_fields && source.contributed_fields.length > 0}
								<div class="mt-1 flex flex-wrap gap-1">
									{#each source.contributed_fields as field}
										<span class="text-xs px-1 py-0.5 bg-green-50 text-green-600 rounded">
											{field}
										</span>
									{/each}
								</div>
							{/if}
						</div>

						{#if isAdmin}
							<div class="flex items-center gap-1">
								{#if !source.is_primary}
									<button
										onclick={() => handleSetPrimary(source.id)}
										class="p-1 text-yellow-500 hover:bg-yellow-50 rounded"
										title="대표 출처로 설정"
									>
										⭐
									</button>
								{/if}
								<button
									onclick={() => handleRemove(source.id)}
									class="p-1 text-red-500 hover:bg-red-50 rounded"
									title="삭제"
								>
									🗑️
								</button>
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}
