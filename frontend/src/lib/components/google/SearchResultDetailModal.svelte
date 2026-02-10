<script lang="ts">
	/**
	 * 검색결과 상세 모달 컴포넌트
	 */
	import type { SearchResultDetail } from '$lib/types';
	import {
		getRankChangeStyle,
		formatRankChange,
		formatDate,
		formatRelativeDate
	} from '$lib/utils/searchResultUtils';
	import Modal from '$lib/components/ui/Modal.svelte';

	interface Props {
		result: SearchResultDetail | null;
		isOpen: boolean;
		onClose: () => void;
		onBookmarkToggle: () => void;
		onReadToggle: () => void;
		onMemoUpdate: (memo: string | null) => void;
	}

	let { result, isOpen, onClose, onBookmarkToggle, onReadToggle, onMemoUpdate }: Props = $props();

	let memoText = $state('');
	let isMemoEditing = $state(false);

	$effect(() => {
		if (result) {
			memoText = result.memo || '';
		}
	});

	function handleMemoSave() {
		onMemoUpdate(memoText || null);
		isMemoEditing = false;
	}

	function openOriginal() {
		if (result) {
			window.open(result.url, '_blank', 'noopener,noreferrer');
		}
	}
</script>

<Modal {isOpen} {onClose} title="검색결과 상세" size="lg">
	{#if result}
		{@const rankStyle = getRankChangeStyle(result)}

		<div class="space-y-4">
			<!-- 제목 & URL -->
			<div>
				<h2 class="text-lg font-bold text-foreground mb-1">{result.title}</h2>
				<a
					href={result.url}
					target="_blank"
					rel="noopener noreferrer"
					class="text-sm text-blue-600 hover:underline break-all"
				>
					{result.url}
				</a>
				{#if result.display_url}
					<p class="text-xs text-muted-foreground mt-1">
						표시 URL: {result.display_url}
					</p>
				{/if}
			</div>

			<!-- 검색 정보 -->
			<div class="bg-muted/50 rounded-lg p-4">
				<h3 class="font-medium text-foreground mb-2">검색 정보</h3>
				<div class="grid grid-cols-2 gap-3 text-sm">
					<div>
						<span class="text-muted-foreground">검색어:</span>
						<span class="font-medium text-primary ml-1">{result.query}</span>
					</div>
					<div>
						<span class="text-muted-foreground">현재 순위:</span>
						<span class="font-bold ml-1">#{result.rank}</span>
						<span class="ml-2 px-2 py-0.5 text-xs rounded-full {rankStyle.color} {rankStyle.bg}">
							{formatRankChange(result)}
						</span>
					</div>
					{#if result.prev_rank !== null}
						<div>
							<span class="text-muted-foreground">이전 순위:</span>
							<span class="ml-1">#{result.prev_rank}</span>
						</div>
					{/if}
					<div>
						<span class="text-muted-foreground">게시일:</span>
						<span class="ml-1">{result.publish_date || '-'}</span>
					</div>
					<div>
						<span class="text-muted-foreground">수집일:</span>
						<span class="ml-1">{formatRelativeDate(result.created_at)}</span>
					</div>
					{#if result.search_date_filter}
						<div>
							<span class="text-muted-foreground">검색 기간:</span>
							<span class="ml-1">{result.search_date_filter}</span>
						</div>
					{/if}
				</div>
			</div>

			<!-- 스니펫 -->
			{#if result.snippet}
				<div>
					<h3 class="font-medium text-foreground mb-2">스니펫</h3>
					<p class="text-sm text-muted-foreground bg-muted/30 rounded-lg p-3">
						{result.snippet}
					</p>
				</div>
			{/if}

			<!-- 순위 히스토리 -->
			{#if result.rank_history && result.rank_history.length > 1}
				<div>
					<h3 class="font-medium text-foreground mb-2">순위 히스토리</h3>
					<div class="space-y-1 max-h-32 overflow-y-auto">
						{#each result.rank_history as history, i}
							<div class="flex justify-between text-sm bg-muted/30 rounded px-3 py-1">
								<span>{formatDate(history.created_at)}</span>
								<span class="font-medium">
									#{history.rank}
									{#if i === 0}
										<span class="text-xs text-primary ml-1">(현재)</span>
									{/if}
								</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- 메모 -->
			<div>
				<div class="flex justify-between items-center mb-2">
					<h3 class="font-medium text-foreground">메모</h3>
					{#if !isMemoEditing}
						<button
							onclick={() => (isMemoEditing = true)}
							class="text-sm text-primary hover:underline"
						>
							수정
						</button>
					{/if}
				</div>
				{#if isMemoEditing}
					<div class="space-y-2">
						<textarea
							bind:value={memoText}
							rows="3"
							placeholder="메모를 입력하세요..."
							class="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary resize-none"
						></textarea>
						<div class="flex gap-2 justify-end">
							<button
								onclick={() => {
									memoText = result?.memo || '';
									isMemoEditing = false;
								}}
								class="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
							>
								취소
							</button>
							<button
								onclick={handleMemoSave}
								class="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
							>
								저장
							</button>
						</div>
					</div>
				{:else}
					<p class="text-sm text-muted-foreground bg-muted/30 rounded-lg p-3 min-h-[60px]">
						{result.memo || '메모가 없습니다.'}
					</p>
				{/if}
			</div>

			<!-- 출처 -->
			<div>
				<h3 class="font-medium text-foreground mb-2">출처</h3>
				<div class="text-sm text-muted-foreground">
					{#if result.saved_search_name}
						<p>저장된 검색: <span class="text-foreground">{result.saved_search_name}</span></p>
					{/if}
					{#if result.schedule_name}
						<p>스케줄: <span class="text-foreground">{result.schedule_name}</span></p>
					{/if}
					{#if !result.saved_search_name && !result.schedule_name}
						<p>-</p>
					{/if}
				</div>
			</div>

			<!-- 액션 버튼 -->
			<div class="flex flex-wrap gap-2 pt-4 border-t border-border">
				<button
					onclick={openOriginal}
					class="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
				>
					원문 보기 ↗
				</button>
				<button
					onclick={onBookmarkToggle}
					class="px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors {result.is_bookmarked
						? 'bg-yellow-50 text-yellow-600'
						: ''}"
				>
					{result.is_bookmarked ? '★ 북마크됨' : '☆ 북마크'}
				</button>
				<button
					onclick={onReadToggle}
					class="px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors {result.is_read
						? 'bg-green-50 text-green-600'
						: ''}"
				>
					{result.is_read ? '✓ 읽음' : '○ 읽음 표시'}
				</button>
			</div>
		</div>
	{/if}
</Modal>
