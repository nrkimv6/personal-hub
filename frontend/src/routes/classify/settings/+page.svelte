<svelte:head><title>설정 — Image Classifier</title></svelte:head>

<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import {
		Settings as SettingsIcon,
		Save,
		RotateCcw,
		FolderSearch,
		Cpu,
		Brain,
		Clock,
		ImageIcon,
		Database
	} from 'lucide-svelte';

	interface Settings {
		scan_root_folders: string[];
		image_extensions: string[];
		max_files_per_scan: number;
		phash_hash_size: number;
		phash_duplicate_threshold: number;
		clip_model_name: string;
		clip_batch_size: number;
		clip_use_gpu: boolean;
		faiss_similarity_threshold: number;
		thumbnail_size: [number, number];
		thumbnail_quality: number;
		ai_mode: string;
		claude_cli_path: string;
		gemini_cli_path: string;
		cli_max_workers: number;
		cli_timeout_seconds: number;
		cluster_gap_minutes: number;
		target_root_folder: string | null;
		use_trash: boolean;
		max_workers_per_task: number;
	}

	let settings: Settings = $state({
		scan_root_folders: [],
		image_extensions: [],
		max_files_per_scan: 300000,
		phash_hash_size: 16,
		phash_duplicate_threshold: 10,
		clip_model_name: 'clip-ViT-B-32',
		clip_batch_size: 64,
		clip_use_gpu: true,
		faiss_similarity_threshold: 0.85,
		thumbnail_size: [300, 300],
		thumbnail_quality: 85,
		ai_mode: 'cli',
		claude_cli_path: 'claude',
		gemini_cli_path: 'gemini',
		cli_max_workers: 2,
		cli_timeout_seconds: 30,
		cluster_gap_minutes: 60,
		target_root_folder: null,
		use_trash: true,
		max_workers_per_task: 4
	});

	let loading = $state(false);
	let saving = $state(false);

	// 추가 UI 전용 상태
	let thumbnailFormat = $state('JPEG');
	let faissType = $state('Flat');
	let faissNlist = $state(100);
	let faissNprobe = $state(10);
	let faissMemoryMap = $state(false);
	let recursiveScan = $state(true);
	let followSymlinks = $state(false);
	let scanDepth = $state(5);
	let vectorDims = $state(512);
	let confidenceThreshold = $state(0.75);
	let autoClusterOnScan = $state(false);
	let thumbnailMaxSize = $state(300);

	onMount(() => {
		loadSettings();
	});

	async function loadSettings() {
		loading = true;
		try {
			const response = await fetchWithTimeout('/api/ic/settings');
			if (response.ok) {
				const data = await response.json();
				settings = { ...settings, ...data };
			}
		} catch (err) {
			console.error('Failed to load settings:', err);
		} finally {
			loading = false;
		}
	}

	async function saveSettings() {
		saving = true;
		try {
			const response = await fetchWithTimeout('/api/ic/settings', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					scan_root_folders: settings.scan_root_folders,
					max_files_per_scan: settings.max_files_per_scan,
					phash_duplicate_threshold: settings.phash_duplicate_threshold,
					clip_batch_size: settings.clip_batch_size,
					clip_use_gpu: settings.clip_use_gpu,
					faiss_similarity_threshold: settings.faiss_similarity_threshold,
					ai_mode: settings.ai_mode,
					cli_max_workers: settings.cli_max_workers,
					cli_timeout_seconds: settings.cli_timeout_seconds,
					cluster_gap_minutes: settings.cluster_gap_minutes,
					target_root_folder: settings.target_root_folder,
					use_trash: settings.use_trash
				})
			});
			if (response.ok) {
				alert('설정이 저장되었습니다.');
			} else {
				alert('설정 저장 실패');
			}
		} catch (err) {
			alert('설정 저장 실패');
		} finally {
			saving = false;
		}
	}

	const hashSizeOptions = [8, 16, 32, 64];
	const aiEngineOptions = ['Claude', 'Gemini'];
	const thumbnailFormatOptions = ['JPEG', 'WebP', 'AVIF'];
	const faissTypeOptions = ['Flat', 'IVF', 'HNSW'];
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<SettingsIcon class="size-5 text-primary" />
				<h1 class="text-2xl font-bold tracking-tight">설정</h1>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">
				이미지 분류기 동작 방식을 세부적으로 조정합니다.
			</p>
		</div>
		<div class="flex items-center gap-2">
			<button
				onclick={loadSettings}
				class="flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted"
			>
				<RotateCcw class="size-3.5" />
				기본값 초기화
			</button>
			<button
				onclick={saveSettings}
				disabled={saving}
				class="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
			>
				<Save class="size-3.5" />
				{saving ? '저장 중...' : '설정 저장'}
			</button>
		</div>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
			<div class="flex items-center gap-2">
				<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
				로딩 중...
			</div>
		</div>
	{:else}
		<!-- 2열 그리드 -->
		<div class="grid gap-6 lg:grid-cols-2">

			<!-- 카드 1: Scan Defaults -->
			<div class="rounded-xl border bg-card p-5">
				<div class="mb-4 flex items-center gap-2">
					<div class="rounded-md bg-primary/10 p-1.5">
						<FolderSearch class="size-4 text-primary" />
					</div>
					<h3 class="text-sm font-semibold">스캔 기본값</h3>
				</div>
				<div class="space-y-3">
					<div class="flex flex-col gap-1">
						<label class="text-xs font-medium" for="max-files">스캔당 최대 파일 수</label>
						<input
							id="max-files"
							type="number"
							bind:value={settings.max_files_per_scan}
							min="1000"
							step="1000"
							class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label class="text-xs font-medium" for="scan-depth">스캔 깊이</label>
						<input
							id="scan-depth"
							type="number"
							bind:value={scanDepth}
							min="1"
							max="10"
							class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
						/>
					</div>
					<div class="flex items-center justify-between rounded-lg border bg-secondary/50 px-3 py-2.5">
						<div>
							<div class="text-xs font-medium">재귀 스캔</div>
							<div class="text-[10px] text-muted-foreground">하위 폴더 포함하여 스캔</div>
						</div>
						<input
							type="checkbox"
							bind:checked={recursiveScan}
							class="size-4 rounded accent-primary"
						/>
					</div>
					<div class="flex items-center justify-between rounded-lg border bg-secondary/50 px-3 py-2.5">
						<div>
							<div class="text-xs font-medium">심볼릭 링크 탐색</div>
							<div class="text-[10px] text-muted-foreground">심볼릭 링크 경로도 탐색</div>
						</div>
						<input
							type="checkbox"
							bind:checked={followSymlinks}
							class="size-4 rounded accent-primary"
						/>
					</div>
				</div>
			</div>

			<!-- 카드 2: Feature Extraction -->
			<div class="rounded-xl border bg-card p-5">
				<div class="mb-4 flex items-center gap-2">
					<div class="rounded-md bg-primary/10 p-1.5">
						<Cpu class="size-4 text-primary" />
					</div>
					<h3 class="text-sm font-semibold">특징 추출</h3>
				</div>
				<div class="space-y-3">
					<div class="flex items-center justify-between rounded-lg border bg-secondary/50 px-3 py-2.5">
						<div>
							<div class="text-xs font-medium">GPU 사용</div>
							<div class="text-[10px] text-muted-foreground">CUDA 가속 활성화 (GPU 필요)</div>
						</div>
						<input
							type="checkbox"
							bind:checked={settings.clip_use_gpu}
							class="size-4 rounded accent-primary"
						/>
					</div>
					<div class="flex flex-col gap-1.5">
						<label class="text-xs font-medium">해시 크기</label>
						<div class="flex overflow-hidden rounded-md border">
							{#each hashSizeOptions as opt}
								<button
									class="flex-1 px-3 py-1.5 text-xs font-medium transition-colors {settings.phash_hash_size === opt ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted'}"
									onclick={() => (settings.phash_hash_size = opt)}
								>{opt}</button>
							{/each}
						</div>
					</div>
					<div class="flex flex-col gap-1">
						<label class="text-xs font-medium" for="vector-dims">벡터 차원</label>
						<input
							id="vector-dims"
							type="number"
							bind:value={vectorDims}
							min="64"
							max="2048"
							step="64"
							class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
						/>
					</div>
				</div>
			</div>

			<!-- 카드 3: AI Configuration -->
			<div class="rounded-xl border bg-card p-5">
				<div class="mb-4 flex items-center gap-2">
					<div class="rounded-md bg-primary/10 p-1.5">
						<Brain class="size-4 text-primary" />
					</div>
					<h3 class="text-sm font-semibold">AI 설정</h3>
				</div>
				<div class="space-y-3">
					<div class="flex flex-col gap-1.5">
						<label class="text-xs font-medium">엔진</label>
						<div class="flex overflow-hidden rounded-md border">
							{#each aiEngineOptions as opt}
								<button
									class="flex-1 px-3 py-1.5 text-xs font-medium transition-colors {settings.ai_mode === opt.toLowerCase() ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted'}"
									onclick={() => (settings.ai_mode = opt.toLowerCase())}
								>{opt}</button>
							{/each}
						</div>
					</div>
					<div class="flex flex-col gap-1">
						<label class="text-xs font-medium" for="timeout">Timeout (초)</label>
						<input
							id="timeout"
							type="number"
							bind:value={settings.cli_timeout_seconds}
							min="10"
							max="300"
							step="5"
							class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label class="text-xs font-medium" for="workers">Workers</label>
						<input
							id="workers"
							type="number"
							bind:value={settings.cli_max_workers}
							min="1"
							max="8"
							class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
						/>
					</div>
					<div class="flex flex-col gap-1">
						<label class="text-xs font-medium" for="confidence">신뢰도 임계값</label>
						<input
							id="confidence"
							type="number"
							bind:value={confidenceThreshold}
							min="0"
							max="1"
							step="0.01"
							class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
						/>
					</div>
				</div>
			</div>

			<!-- 카드 4: Clustering -->
			<div class="rounded-xl border bg-card p-5">
				<div class="mb-4 flex items-center gap-2">
					<div class="rounded-md bg-primary/10 p-1.5">
						<Clock class="size-4 text-primary" />
					</div>
					<h3 class="text-sm font-semibold">클러스터링</h3>
				</div>
				<div class="space-y-3">
					<div class="flex flex-col gap-1.5">
						<div class="flex items-center justify-between">
							<label class="text-xs font-medium" for="gap-slider">클러스터 간격</label>
							<span class="text-xs font-bold text-primary">{settings.cluster_gap_minutes}min</span>
						</div>
						<input
							id="gap-slider"
							type="range"
							min="5"
							max="120"
							step="5"
							bind:value={settings.cluster_gap_minutes}
							class="accent-primary"
						/>
						<div class="flex justify-between text-[10px] text-muted-foreground">
							<span>5min</span>
							<span>120min</span>
						</div>
					</div>
					<div class="flex items-center justify-between rounded-lg border bg-secondary/50 px-3 py-2.5">
						<div>
							<div class="text-xs font-medium">스캔 후 자동 클러스터링</div>
							<div class="text-[10px] text-muted-foreground">스캔 완료 후 자동 클러스터링</div>
						</div>
						<input
							type="checkbox"
							bind:checked={autoClusterOnScan}
							class="size-4 rounded accent-primary"
						/>
					</div>
				</div>
			</div>

			<!-- 카드 5: Thumbnails -->
			<div class="rounded-xl border bg-card p-5">
				<div class="mb-4 flex items-center gap-2">
					<div class="rounded-md bg-primary/10 p-1.5">
						<ImageIcon class="size-4 text-primary" />
					</div>
					<h3 class="text-sm font-semibold">썸네일</h3>
				</div>
				<div class="space-y-3">
					<div class="flex flex-col gap-1.5">
						<div class="flex items-center justify-between">
							<label class="text-xs font-medium" for="quality-slider">품질</label>
							<span class="text-xs font-bold text-primary">{settings.thumbnail_quality}</span>
						</div>
						<input
							id="quality-slider"
							type="range"
							min="0"
							max="100"
							step="5"
							bind:value={settings.thumbnail_quality}
							class="accent-primary"
						/>
					</div>
					<div class="flex flex-col gap-1.5">
						<div class="flex items-center justify-between">
							<label class="text-xs font-medium" for="size-slider">최대 크기(px)</label>
							<span class="text-xs font-bold text-primary">{thumbnailMaxSize}px</span>
						</div>
						<input
							id="size-slider"
							type="range"
							min="100"
							max="800"
							step="50"
							bind:value={thumbnailMaxSize}
							class="accent-primary"
						/>
					</div>
					<div class="flex flex-col gap-1.5">
						<label class="text-xs font-medium">형식</label>
						<div class="flex overflow-hidden rounded-md border">
							{#each thumbnailFormatOptions as opt}
								<button
									class="flex-1 px-3 py-1.5 text-xs font-medium transition-colors {thumbnailFormat === opt ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted'}"
									onclick={() => (thumbnailFormat = opt)}
								>{opt}</button>
							{/each}
						</div>
					</div>
				</div>
			</div>

			<!-- 카드 6: FAISS Index -->
			<div class="rounded-xl border bg-card p-5">
				<div class="mb-4 flex items-center gap-2">
					<div class="rounded-md bg-primary/10 p-1.5">
						<Database class="size-4 text-primary" />
					</div>
					<h3 class="text-sm font-semibold">FAISS 인덱스</h3>
				</div>
				<div class="space-y-3">
					<div class="flex flex-col gap-1.5">
						<label class="text-xs font-medium">인덱스 타입</label>
						<div class="flex overflow-hidden rounded-md border">
							{#each faissTypeOptions as opt}
								<button
									class="flex-1 px-3 py-1.5 text-xs font-medium transition-colors {faissType === opt ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted'}"
									onclick={() => (faissType = opt)}
								>{opt}</button>
							{/each}
						</div>
					</div>
					<div class="grid grid-cols-2 gap-3">
						<div class="flex flex-col gap-1">
							<label class="text-xs font-medium" for="nlist">nlist</label>
							<input
								id="nlist"
								type="number"
								bind:value={faissNlist}
								min="10"
								max="1000"
								class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
							/>
						</div>
						<div class="flex flex-col gap-1">
							<label class="text-xs font-medium" for="nprobe">nprobe</label>
							<input
								id="nprobe"
								type="number"
								bind:value={faissNprobe}
								min="1"
								max="100"
								class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
							/>
						</div>
					</div>
					<div class="flex items-center justify-between rounded-lg border bg-secondary/50 px-3 py-2.5">
						<div>
							<div class="text-xs font-medium">메모리 맵</div>
							<div class="text-[10px] text-muted-foreground">mmap으로 인덱스 파일 로드 (대용량)</div>
						</div>
						<input
							type="checkbox"
							bind:checked={faissMemoryMap}
							class="size-4 rounded accent-primary"
						/>
					</div>
				</div>
			</div>

		</div>
	{/if}
</div>
