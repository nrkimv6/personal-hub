<script lang="ts">
	import { Button } from '$lib/components/ui';

	import { onMount } from 'svelte';
	import { collectApi } from '$lib/api';
	import type { InstagramTag, InstagramKeyword } from '$lib/types';

	let tags: InstagramTag[] = [];
	let loading = true;
	let error: string | null = null;

	// 선택된 태그
	let selectedTag: InstagramTag | null = null;
	let keywords: InstagramKeyword[] = [];
	let loadingKeywords = false;

	// 새 태그 생성
	let showCreateTagModal = false;
	let newTagName = '';
	let newTagDisplayName = '';
	let newTagDescription = '';
	let newTagColor = '#3B82F6';

	// 새 키워드 추가
	let newKeyword = '';
	let newKeywordIsRegex = false;
	let newKeywordCaseSensitive = false;

	// 재분류
	let reclassifying = false;

	async function fetchTags() {
		loading = true;
		try {
			tags = await collectApi.tags.getTags(true);
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '태그 목록 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function selectTag(tag: InstagramTag) {
		selectedTag = tag;
		loadingKeywords = true;
		try {
			keywords = await collectApi.tags.getKeywords(tag.id, true);
		} catch (e) {
			console.error('키워드 로드 실패:', e);
			keywords = [];
		} finally {
			loadingKeywords = false;
		}
	}

	async function createTag() {
		if (!newTagName.trim()) return;
		try {
			await collectApi.tags.createTag({
				name: newTagName.trim(),
				display_name: newTagDisplayName.trim() || newTagName.trim(),
				description: newTagDescription.trim() || undefined,
				color: newTagColor
			});
			showCreateTagModal = false;
			newTagName = '';
			newTagDisplayName = '';
			newTagDescription = '';
			newTagColor = '#3B82F6';
			await fetchTags();
		} catch (e) {
			alert('태그 생성 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function deleteTag(tagId: number) {
		if (!confirm('이 태그를 삭제하시겠습니까? 관련 키워드와 분류도 모두 삭제됩니다.')) return;
		try {
			await collectApi.tags.deleteTag(tagId);
			if (selectedTag?.id === tagId) {
				selectedTag = null;
				keywords = [];
			}
			await fetchTags();
		} catch (e) {
			alert('태그 삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function addKeyword() {
		if (!selectedTag || !newKeyword.trim()) return;
		try {
			await collectApi.tags.addKeyword(selectedTag.id, {
				keyword: newKeyword.trim(),
				is_regex: newKeywordIsRegex,
				is_case_sensitive: newKeywordCaseSensitive
			});
			newKeyword = '';
			newKeywordIsRegex = false;
			newKeywordCaseSensitive = false;
			keywords = await collectApi.tags.getKeywords(selectedTag.id, true);
		} catch (e) {
			alert('키워드 추가 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function deleteKeyword(keywordId: number) {
		if (!confirm('이 키워드를 삭제하시겠습니까?')) return;
		try {
			await collectApi.tags.deleteKeyword(keywordId);
			if (selectedTag) {
				keywords = await collectApi.tags.getKeywords(selectedTag.id, true);
			}
		} catch (e) {
			alert('키워드 삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function toggleKeyword(keywordId: number) {
		try {
			await collectApi.tags.toggleKeyword(keywordId);
			if (selectedTag) {
				keywords = await collectApi.tags.getKeywords(selectedTag.id, true);
			}
		} catch (e) {
			alert('키워드 상태 변경 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function reclassifyAll() {
		if (!confirm('전체 게시물을 재분류하시겠습니까? 기존 분류가 초기화됩니다.')) return;
		reclassifying = true;
		try {
			const result = await collectApi.tags.reclassifyAll();
			alert(`재분류 완료: ${result.classified}/${result.total}개 게시물 분류됨`);
		} catch (e) {
			alert('재분류 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			reclassifying = false;
		}
	}

	onMount(() => {
		fetchTags();
	});
</script>

<div>
	<div class="mb-6 flex justify-end">
		<div class="flex gap-2">
			<Button variant="secondary" size="sm" on:click={reclassifyAll} disabled={reclassifying}>
				{reclassifying ? '재분류 중...' : '전체 재분류'}
			</Button>
			<Button variant="primary" size="sm" on:click={() => (showCreateTagModal = true)}>
				+ 새 태그
			</Button>
		</div>
	</div>

	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else}
		<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
			<!-- 태그 목록 -->
			<div class="card">
				<h3 class="text-lg font-semibold mb-4">태그 목록</h3>
				{#if tags.length === 0}
					<p class="text-muted-foreground text-sm">등록된 태그가 없습니다</p>
				{:else}
					<div class="space-y-2">
						{#each tags as tag (tag.id)}
							<div
								class="flex items-center justify-between p-2 rounded-lg cursor-pointer transition-colors {selectedTag?.id ===
								tag.id
									? 'bg-primary-light border border-blue-200'
									: 'hover:bg-muted'}"
								onclick={() => selectTag(tag)}
								onkeydown={(e) => e.key === 'Enter' && selectTag(tag)}
								role="button"
								tabindex="0"
							>
								<div class="flex items-center gap-2">
									<span
										class="w-3 h-3 rounded-full"
										style="background-color: {tag.color};"
									></span>
									<span class="font-medium">{tag.display_name}</span>
									<span class="text-xs text-muted-foreground">({tag.keyword_count})</span>
								</div>
								<button
									onclick={(e) => {
										e.stopPropagation();
										deleteTag(tag.id);
									}}
									class="text-error hover:text-error text-sm"
								>
									삭제
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- 키워드 목록 -->
			<div class="card lg:col-span-2">
				{#if selectedTag}
					<div class="flex justify-between items-center mb-4">
						<h3 class="text-lg font-semibold">
							<span
								class="inline-block w-3 h-3 rounded-full mr-2"
								style="background-color: {selectedTag.color};"
							></span>
							{selectedTag.display_name} 키워드
						</h3>
					</div>

					<!-- 키워드 추가 폼 -->
					<div class="mb-4 p-3 bg-background rounded-lg">
						<div class="flex flex-wrap gap-2 items-end">
							<div class="flex-1 min-w-48">
								<label for="new-keyword" class="block text-xs text-muted-foreground mb-1">키워드</label>
								<input
									id="new-keyword"
									type="text"
									bind:value={newKeyword}
									placeholder="새 키워드 입력"
									class="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
									onkeydown={(e) => e.key === 'Enter' && addKeyword()}
								/>
							</div>
							<label class="flex items-center gap-1 text-sm">
								<input type="checkbox" bind:checked={newKeywordIsRegex} />
								정규식
							</label>
							<label class="flex items-center gap-1 text-sm">
								<input type="checkbox" bind:checked={newKeywordCaseSensitive} />
								대소문자 구분
							</label>
							<Button variant="primary" size="sm" on:click={addKeyword}> 추가 </Button>
						</div>
					</div>

					<!-- 키워드 목록 -->
					{#if loadingKeywords}
						<div class="text-center py-4">
							<div
								class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mx-auto"
							></div>
						</div>
					{:else if keywords.length === 0}
						<p class="text-muted-foreground text-sm text-center py-4">등록된 키워드가 없습니다</p>
					{:else}
						<div class="space-y-1">
							{#each keywords as kw (kw.id)}
								<div
									class="flex items-center justify-between p-2 rounded-lg {kw.is_active
										? 'bg-white'
										: 'bg-muted opacity-60'}"
								>
									<div class="flex items-center gap-2">
										<code class="text-sm px-2 py-0.5 bg-muted rounded">{kw.keyword}</code>
										{#if kw.is_regex}
											<span class="text-xs px-1.5 py-0.5 bg-purple-light text-purple rounded"
												>정규식</span
											>
										{/if}
										{#if kw.is_case_sensitive}
											<span class="text-xs px-1.5 py-0.5 bg-warning-light text-warning rounded"
												>대소문자 구분</span
											>
										{/if}
									</div>
									<div class="flex items-center gap-2">
										<button
											onclick={() => toggleKeyword(kw.id)}
											class="text-sm {kw.is_active
												? 'text-warning-foreground hover:text-warning'
												: 'text-success hover:text-success'}"
										>
											{kw.is_active ? '비활성화' : '활성화'}
										</button>
										<button
											onclick={() => deleteKeyword(kw.id)}
											class="text-error hover:text-error text-sm"
										>
											삭제
										</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				{:else}
					<div class="text-center py-12 text-muted-foreground">
						<p>왼쪽에서 태그를 선택하세요</p>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<!-- 새 태그 생성 모달 -->
{#if showCreateTagModal}
	<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl max-w-md w-full">
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<h3 class="text-lg font-bold text-foreground">새 태그 생성</h3>
					<button
						onclick={() => (showCreateTagModal = false)}
						class="text-muted-foreground hover:text-muted-foreground text-2xl"
					>
						&times;
					</button>
				</div>

				<div class="space-y-4">
					<div>
						<label for="new-tag-name" class="block text-sm font-medium text-foreground mb-1">태그 ID (영문)</label>
						<input
							id="new-tag-name"
							type="text"
							bind:value={newTagName}
							placeholder="예: event, popup_store"
							class="w-full px-3 py-2 border border-border rounded-lg"
						/>
					</div>
					<div>
						<label for="new-tag-display-name" class="block text-sm font-medium text-foreground mb-1">표시 이름</label>
						<input
							id="new-tag-display-name"
							type="text"
							bind:value={newTagDisplayName}
							placeholder="예: 이벤트, 팝업스토어"
							class="w-full px-3 py-2 border border-border rounded-lg"
						/>
					</div>
					<div>
						<label for="new-tag-description" class="block text-sm font-medium text-foreground mb-1">설명 (선택)</label>
						<input
							id="new-tag-description"
							type="text"
							bind:value={newTagDescription}
							placeholder="태그 설명"
							class="w-full px-3 py-2 border border-border rounded-lg"
						/>
					</div>
					<div>
						<label for="new-tag-color" class="block text-sm font-medium text-foreground mb-1">색상</label>
						<div class="flex items-center gap-2">
							<input id="new-tag-color" type="color" bind:value={newTagColor} class="w-10 h-10 rounded" />
							<span class="text-sm text-muted-foreground">{newTagColor}</span>
						</div>
					</div>
				</div>

				<div class="mt-6 flex justify-end gap-2">
					<Button variant="secondary" size="sm" on:click={() => (showCreateTagModal = false)}>
						취소
					</Button>
					<Button variant="primary" size="sm" on:click={createTag}> 생성 </Button>
				</div>
			</div>
		</div>
	</div>
{/if}
