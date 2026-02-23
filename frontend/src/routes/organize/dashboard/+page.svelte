<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { Play, Square, RefreshCw, HardDrive, Music, Archive, FileText, Terminal, Gamepad2, FolderQuestion } from 'lucide-svelte';

	// 상태
	let stats = $state<any>(null);
	let scanStatus = $state<any>(null);
	let isLoading = $state(true);
	let isScanRunning = $state(false);
	let scanRootInput = $state('');
	let error = $state<string | null>(null);

	let pollInterval: ReturnType<typeof setInterval> | null = null;

	const FILE_GROUP_ICONS: Record<string, any> = {
		music: Music,
		archive: Archive,
		document: FileText,
		installer: Terminal,
		game: Gamepad2,
		misc: FolderQuestion
	};

	const FILE_GROUP_LABELS: Record<string, string> = {
		music: '음악',
		archive: '압축파일',
		document: '문서',
		installer: '설치파일',
		game: '게임',
		misc: '기타'
	};

	async function fetchStats() {
		try {
			const [statsRes, scanRes] = await Promise.all([
				fetch('/api/fc/stats'),
				fetch('/api/fc/scan/status')
			]);
			if (statsRes.ok) stats = await statsRes.json();
			if (scanRes.ok) {
				scanStatus = await scanRes.json();
				isScanRunning = scanStatus?.is_running ?? false;
			}
		} catch (e) {
			error = '데이터 로드 실패';
		} finally {
			isLoading = false;
		}
	}

	async function startScan() {
		const rootFolders = scanRootInput
			.split('\n')
			.map((s: string) => s.trim())
			.filter(Boolean);

		const res = await fetch('/api/fc/scan/start', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ root_folders: rootFolders.length > 0 ? rootFolders : null })
		});
		const data = await res.json();
		if (data.status === 'started' || data.status === 'already_running') {
			isScanRunning = true;
		}
	}

	async function stopScan() {
		await fetch('/api/fc/scan/stop', { method: 'POST' });
	}

	function formatSize(bytes: number): string {
		if (!bytes) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		let i = 0;
		while (bytes >= 1024 && i < units.length - 1) {
			bytes /= 1024;
			i++;
		}
		return `${bytes.toFixed(1)} ${units[i]}`;
	}

	onMount(() => {
		fetchStats();
		pollInterval = setInterval(fetchStats, 3000);
	});

	onDestroy(() => {
		if (pollInterval) clearInterval(pollInterval);
	});
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-xl font-bold text-foreground">파일 정리기 대시보드</h2>
			<p class="text-sm text-muted-foreground">PC 파일을 스캔하고 자동 분류합니다</p>
		</div>
		<button
			onclick={fetchStats}
			class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
		>
			<RefreshCw class="size-4" />
			새로고침
		</button>
	</div>

	<!-- 스캔 컨트롤 -->
	<div class="rounded-lg border border-border bg-card p-4">
		<h3 class="mb-3 text-sm font-semibold text-foreground">스캔 시작</h3>
		<div class="flex gap-3">
			<textarea
				bind:value={scanRootInput}
				placeholder="스캔할 폴더 경로 (줄바꿈으로 여러 개 입력, 비우면 설정값 사용)"
				class="flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
				rows={2}
			></textarea>
			<div class="flex flex-col gap-2">
				{#if isScanRunning}
					<button
						onclick={stopScan}
						class="flex items-center gap-1.5 rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90"
					>
						<Square class="size-4" />
						중지
					</button>
				{:else}
					<button
						onclick={startScan}
						class="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
					>
						<Play class="size-4" />
						스캔 시작
					</button>
				{/if}
			</div>
		</div>

		<!-- 스캔 진행 상황 -->
		{#if scanStatus?.is_running}
			<div class="mt-3">
				<div class="mb-1 flex justify-between text-xs text-muted-foreground">
					<span>{scanStatus.current_file ?? '스캔 중...'}</span>
					<span>{scanStatus.processed_files} / {scanStatus.total_files} ({scanStatus.progress_percent}%)</span>
				</div>
				<div class="h-2 w-full overflow-hidden rounded-full bg-muted">
					<div
						class="h-full bg-primary transition-all"
						style="width: {scanStatus.progress_percent ?? 0}%"
					></div>
				</div>
			</div>
		{/if}
	</div>

	<!-- 통계 카드 -->
	{#if isLoading}
		<div class="text-center text-sm text-muted-foreground">로딩 중...</div>
	{:else if error}
		<div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>
	{:else if stats}
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
			{#each (stats.by_group ?? []) as group}
				{@const Icon = FILE_GROUP_ICONS[group.file_group] ?? FolderQuestion}
				<div class="rounded-lg border border-border bg-card p-3">
					<div class="mb-2 flex items-center gap-2">
						<Icon class="size-4 text-primary" />
						<span class="text-xs font-medium text-muted-foreground">{FILE_GROUP_LABELS[group.file_group] ?? group.file_group}</span>
					</div>
					<p class="text-lg font-bold text-foreground">{group.count.toLocaleString()}</p>
					<p class="text-xs text-muted-foreground">{formatSize(group.total_size)}</p>
				</div>
			{/each}
		</div>

		<!-- 전체 합계 -->
		<div class="rounded-lg border border-border bg-card p-4">
			<div class="flex items-center gap-6">
				<div>
					<p class="text-xs text-muted-foreground">전체 파일</p>
					<p class="text-2xl font-bold text-foreground">{(stats.total_files ?? 0).toLocaleString()}</p>
				</div>
				<div>
					<p class="text-xs text-muted-foreground">전체 크기</p>
					<p class="text-2xl font-bold text-foreground">{formatSize(stats.total_size ?? 0)}</p>
				</div>
			</div>
		</div>
	{/if}
</div>
