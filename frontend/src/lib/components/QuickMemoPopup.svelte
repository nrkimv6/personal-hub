<script lang="ts">
	import { onMount } from 'svelte';
	import { quickMemo, closeQuickMemo } from '$lib/stores/quickMemo';
	import { notesApi } from '$lib/api/notes';
	import type { TagDef } from '$lib/api/notes';
	import { toast } from '$lib/stores/toast';
	import MenuPicker from '../../routes/notes/components/MenuPicker.svelte';
	import { navEntries, isNavGroup } from '$lib/navigation';
	import type { NavSingleItem } from '$lib/navigation';

	// 팝업 상태
	let title = $state('');
	let content = $state('');
	let selectedTagIds = $state<number[]>([]);
	let recentTags = $state<TagDef[]>([]);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let showMenuPicker = $state(false);

	// 연결 메뉴 (store에서 초기화)
	let linkedMenuId = $state<string | null>(null);
	let linkedMenuLabel = $state<string | null>(null);

	// 메뉴 아이콘 조회
	function getMenuIcon(menuId: string | null): string {
		if (!menuId) return '';
		const item = navEntries
			.filter((e): e is NavSingleItem => !isNavGroup(e))
			.find((e) => e.id === menuId);
		return item?.icon ?? '';
	}

	// store 변경 시 로컬 상태 동기화
	$effect(() => {
		if ($quickMemo.open) {
			linkedMenuId = $quickMemo.linkedMenuId;
			linkedMenuLabel = $quickMemo.linkedMenuLabel;
			// 팝업 열릴 때 태그 로드
			loadTags();
			// 폼 초기화
			title = '';
			content = '';
			selectedTagIds = [];
			error = null;
			showMenuPicker = false;
		}
	});

	async function loadTags() {
		try {
			const tags = await notesApi.listTags();
			// note_count 기준 상위 5개
			recentTags = tags.sort((a, b) => b.note_count - a.note_count).slice(0, 5);
		} catch {
			// 태그 로드 실패는 무시
		}
	}

	function toggleTag(id: number) {
		if (selectedTagIds.includes(id)) {
			selectedTagIds = selectedTagIds.filter((t) => t !== id);
		} else {
			selectedTagIds = [...selectedTagIds, id];
		}
	}

	async function save() {
		if (!title.trim()) {
			error = '제목을 입력해주세요.';
			return;
		}
		saving = true;
		error = null;
		try {
			await notesApi.create({
				title: title.trim(),
				content: content.trim() || undefined,
				tag_ids: selectedTagIds.length > 0 ? selectedTagIds : undefined,
				linked_menu_id: linkedMenuId ?? undefined,
				linked_tab: $quickMemo.linkedTab ?? undefined
			});
			toast.success('메모가 저장되었습니다');
			closeQuickMemo();
		} catch (e) {
			error = e instanceof Error ? e.message : '저장에 실패했습니다.';
		} finally {
			saving = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
			e.preventDefault();
			save();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			if (showMenuPicker) {
				showMenuPicker = false;
			} else {
				closeQuickMemo();
			}
		}
	}

	function handleTitleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			save();
		}
	}

	function handleTextareaKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
			e.preventDefault();
			save();
		}
	}

	function handleMenuPickerSelect(menuId: string | null) {
		linkedMenuId = menuId;
		if (menuId) {
			const item = navEntries
				.filter((e): e is NavSingleItem => !isNavGroup(e))
				.find((e) => e.id === menuId);
			linkedMenuLabel = item?.label ?? null;
		} else {
			linkedMenuLabel = null;
		}
		showMenuPicker = false;
	}
</script>

{#if $quickMemo.open}
	<!-- 배경 클릭 시 닫기 -->
	<button
		class="fixed inset-0 z-40"
		onclick={closeQuickMemo}
		aria-label="팝업 닫기"
		tabindex="-1"
	></button>

	<!-- 팝업 본체 -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed bottom-4 right-4 z-50 w-full max-w-[400px] rounded-xl shadow-modal bg-card border border-border flex flex-col"
		onkeydown={handleKeydown}
		role="dialog"
		aria-modal="true"
		aria-label="빠른 메모"
	>
		<!-- 헤더 -->
		<div class="flex items-center justify-between px-4 py-3 border-b border-border">
			<div class="flex items-center gap-2">
				<span class="font-semibold text-foreground text-sm">⚡ 빠른 메모</span>
				{#if linkedMenuId}
					<span class="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full flex items-center gap-1">
						🔗 {getMenuIcon(linkedMenuId)}{linkedMenuLabel}
					</span>
				{/if}
			</div>
			<button
				onclick={closeQuickMemo}
				class="text-muted-foreground hover:text-foreground w-6 h-6 flex items-center justify-center rounded"
				aria-label="닫기"
			>✕</button>
		</div>

		<!-- 본문 -->
		<div class="flex flex-col gap-3 p-4">
			<!-- 제목 -->
			<input
				type="text"
				class="w-full bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
				placeholder="제목 (필수)"
				maxlength={200}
				bind:value={title}
				onkeydown={handleTitleKeydown}
				autofocus
			/>

			<!-- 내용 -->
			<textarea
				class="w-full bg-muted border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary resize-none"
				placeholder="내용 (선택, Shift+Enter=줄바꿈)"
				style="min-height: 120px;"
				bind:value={content}
				onkeydown={handleTextareaKeydown}
			></textarea>

			<!-- 태그 빠른 선택 -->
			{#if recentTags.length > 0}
				<div class="flex flex-wrap gap-1.5">
					{#each recentTags as tag}
						<button
							type="button"
							class="px-2 py-0.5 text-xs rounded-full border transition-colors"
							style="border-color: {tag.color}; color: {selectedTagIds.includes(tag.id) ? '#fff' : tag.color}; background: {selectedTagIds.includes(tag.id) ? tag.color : 'transparent'};"
							onclick={() => toggleTag(tag.id)}
						>
							{tag.name}
						</button>
					{/each}
				</div>
			{/if}

			<!-- 연결 메뉴 변경 -->
			<div class="relative">
				<button
					type="button"
					class="text-xs text-muted-foreground hover:text-foreground underline"
					onclick={() => (showMenuPicker = !showMenuPicker)}
				>
					{linkedMenuId ? '연결 메뉴 변경' : '+ 메뉴 연결'}
				</button>

				{#if showMenuPicker}
					<div class="absolute bottom-full mb-1 left-0 z-10">
						<MenuPicker
							selectedMenuId={linkedMenuId}
							onSelect={handleMenuPickerSelect}
						/>
					</div>
				{/if}
			</div>

			<!-- 에러 -->
			{#if error}
				<p class="text-xs text-destructive">{error}</p>
			{/if}

			<!-- 버튼 -->
			<div class="flex justify-end gap-2 pt-1">
				<button
					type="button"
					class="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted"
					onclick={closeQuickMemo}
				>
					Esc 취소
				</button>
				<button
					type="button"
					class="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50"
					onclick={save}
					disabled={saving}
				>
					{saving ? '저장 중...' : 'Enter 저장'}
				</button>
			</div>
		</div>
	</div>
{/if}
