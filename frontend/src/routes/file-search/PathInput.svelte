<script lang="ts">
	import { browseDirectory } from '$lib/api/fileSearch';
	import type { DirectoryItem } from '$lib/types/fileSearch';

	interface Props {
		path: string;
		onchange: (path: string) => void;
	}

	let { path = $bindable(''), onchange }: Props = $props();

	let showModal = $state(false);
	let browsePath = $state('');
	let browseParent: string | null = $state(null);
	let directories: DirectoryItem[] = $state([]);
	let browseLoading = $state(false);
	let browseError = $state('');

	async function openBrowser() {
		showModal = true;
		browsePath = path || '';
		await loadDirectory(browsePath);
	}

	async function loadDirectory(targetPath: string) {
		browseLoading = true;
		browseError = '';
		try {
			const res = await browseDirectory(targetPath);
			browsePath = res.current;
			browseParent = res.parent;
			directories = res.directories;
		} catch (e) {
			browseError = '디렉토리 목록을 불러오지 못했습니다.';
		} finally {
			browseLoading = false;
		}
	}

	function selectDir(item: DirectoryItem) {
		loadDirectory(item.path);
	}

	function confirmSelect() {
		onchange(browsePath);
		path = browsePath;
		showModal = false;
	}

	function closeModal() {
		showModal = false;
	}
</script>

<div class="flex items-center gap-2">
	<input
		bind:value={path}
		type="text"
		placeholder="경로 직접 입력 (예: D:\work\project)"
		class="flex-1 rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm
			   outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary/20"
		oninput={() => onchange(path)}
	/>
	<button
		onclick={openBrowser}
		class="rounded-lg border border-border bg-background px-3 py-2 text-sm
			   transition-colors hover:bg-muted"
		title="폴더 브라우저 열기"
	>
		📁
	</button>
	{#if path}
		<button
			onclick={() => { path = ''; onchange(''); }}
			class="rounded-lg border border-border bg-background px-2 py-2 text-xs
				   text-muted-foreground transition-colors hover:text-destructive"
			title="경로 지우기"
		>
			×
		</button>
	{/if}
</div>

<!-- 폴더 브라우저 모달 -->
{#if showModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		role="dialog"
		aria-modal="true"
	>
		<div class="w-[500px] max-h-[80vh] flex flex-col rounded-xl border border-border bg-card shadow-xl">
			<!-- 헤더 -->
			<div class="flex items-center justify-between border-b border-border px-4 py-3">
				<h3 class="font-medium">폴더 선택</h3>
				<button onclick={closeModal} class="text-muted-foreground hover:text-foreground text-lg leading-none">×</button>
			</div>

			<!-- 현재 경로 -->
			<div class="border-b border-border bg-muted/30 px-4 py-2 font-mono text-xs text-muted-foreground truncate">
				{browsePath || '드라이브 선택'}
			</div>

			<!-- 디렉토리 목록 -->
			<div class="flex-1 overflow-y-auto py-1">
				{#if browseLoading}
					<div class="flex items-center justify-center py-8 text-sm text-muted-foreground">로딩 중...</div>
				{:else if browseError}
					<div class="px-4 py-4 text-sm text-destructive">{browseError}</div>
				{:else}
					<!-- 상위 폴더 이동 -->
					{#if browseParent !== null}
						<button
							onclick={() => loadDirectory(browseParent!)}
							class="flex w-full items-center gap-2 px-4 py-2 text-sm text-muted-foreground
								   hover:bg-muted transition-colors"
						>
							📁 <span class="font-mono">../</span>
						</button>
					{/if}

					{#if directories.length === 0}
						<div class="px-4 py-4 text-sm text-muted-foreground">하위 폴더가 없습니다.</div>
					{:else}
						{#each directories as dir}
							<button
								onclick={() => selectDir(dir)}
								class="flex w-full items-center gap-2 px-4 py-2 text-sm
									   hover:bg-muted transition-colors truncate"
							>
								📁 <span class="font-mono">{dir.name}</span>
							</button>
						{/each}
					{/if}
				{/if}
			</div>

			<!-- 푸터 -->
			<div class="flex items-center justify-between border-t border-border px-4 py-3">
				<span class="font-mono text-xs text-muted-foreground truncate max-w-[280px]">
					{browsePath || '선택 없음'}
				</span>
				<div class="flex gap-2">
					<button
						onclick={closeModal}
						class="rounded-lg border border-border px-3 py-1.5 text-sm transition-colors hover:bg-muted"
					>
						취소
					</button>
					<button
						onclick={confirmSelect}
						disabled={!browsePath}
						class="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground
							   transition-colors hover:bg-primary/90 disabled:opacity-50"
					>
						선택
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
