<script lang="ts">
	import { onMount } from 'svelte';
	import { AlertTriangle, Download, FileText, Loader2, Trash2, Upload } from 'lucide-svelte';

	import {
		convertToPdf,
		getHealth,
		type ImagePdfConvertOptions,
		type ImagePdfHealthResponse
	} from '$lib/api/image-pdf';
	import { toast } from '$lib/stores/toast';

	const DEFAULT_OPTIONS: ImagePdfConvertOptions = {
		bw: false,
		white: 200,
		black: 80,
		quality: 85,
		preserveDpi: false,
		outputName: ''
	};

	let selectedFiles: File[] = $state([]);
	let options: ImagePdfConvertOptions = $state({ ...DEFAULT_OPTIONS });
	let health: ImagePdfHealthResponse | null = $state(null);
	let loading = $state(false);
	let errorMessage = $state('');
	let dragActive = $state(false);
	let lastDownloadName = $state('');

	const canConvert = $derived(selectedFiles.length > 0 && !loading);

	function formatBytes(bytes: number): string {
		if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
		if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
		return `${bytes} B`;
	}

	function setFiles(files: FileList | File[]) {
		selectedFiles = Array.from(files);
		errorMessage = '';
		lastDownloadName = '';
	}

	function handleFileInput(event: Event) {
		const target = event.currentTarget as HTMLInputElement;
		if (target.files) setFiles(target.files);
	}

	function handleDragOver(event: DragEvent) {
		event.preventDefault();
		dragActive = true;
	}

	function handleDragLeave(event: DragEvent) {
		event.preventDefault();
		dragActive = false;
	}

	function handleDrop(event: DragEvent) {
		event.preventDefault();
		dragActive = false;
		const files = event.dataTransfer?.files;
		if (files?.length) setFiles(files);
	}

	function removeFile(index: number) {
		selectedFiles = selectedFiles.filter((_, itemIndex) => itemIndex !== index);
	}

	function clampOptions() {
		options.white = Math.max(0, Math.min(255, Number(options.white)));
		options.black = Math.max(0, Math.min(255, Number(options.black)));
		options.quality = Math.max(1, Math.min(100, Number(options.quality)));
	}

	function downloadBlob(blob: Blob, filename: string) {
		const url = URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.href = url;
		link.download = filename;
		document.body.appendChild(link);
		link.click();
		link.remove();
		URL.revokeObjectURL(url);
	}

	async function handleSubmit() {
		if (!canConvert) return;
		clampOptions();
		if (options.white <= options.black) {
			toast.warning('흰색 임계값은 검정 임계값보다 커야 합니다.');
			return;
		}

		loading = true;
		errorMessage = '';
		lastDownloadName = '';
		try {
			const result = await convertToPdf(selectedFiles, options);
			downloadBlob(result.blob, result.filename);
			lastDownloadName = result.filename;
			toast.success('PDF 변환이 완료되었습니다.');
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : 'PDF 변환에 실패했습니다.';
			toast.error(errorMessage);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void (async () => {
			try {
				health = await getHealth();
			} catch (error) {
				errorMessage = error instanceof Error ? error.message : 'image-pdf 상태를 불러오지 못했습니다.';
			}
		})();
	});
</script>

{#if health && !health.heic_supported}
	<div class="rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
		<div class="flex items-start gap-2">
			<AlertTriangle size={18} class="mt-0.5 shrink-0" />
			<div>
				<div class="font-semibold">HEIC/HEIF 변환 미지원</div>
				<div>현재 서버에는 HEIC opener가 없어 jpg, png, webp 등 일반 이미지 형식만 변환됩니다.</div>
			</div>
		</div>
	</div>
{/if}

{#if errorMessage}
	<div class="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
		{errorMessage}
	</div>
{/if}

<section class="grid gap-6 lg:grid-cols-[minmax(0,440px)_minmax(0,1fr)]">
	<div class="rounded-2xl border border-border bg-card p-5 shadow-sm">
		<h2 class="text-base font-semibold">이미지 업로드</h2>
		<p class="mt-1 text-sm text-muted-foreground">
			선택한 순서대로 이미지를 하나의 PDF로 병합합니다.
		</p>

		<div
			class={`mt-4 rounded-2xl border-2 border-dashed p-6 text-center transition ${
				dragActive ? 'border-primary bg-primary/5' : 'border-border'
			}`}
			ondragover={handleDragOver}
			ondragleave={handleDragLeave}
			ondrop={handleDrop}
		>
			<div class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
				<Upload size={22} />
			</div>
			<div class="mt-3 text-sm font-medium">이미지를 끌어놓거나 직접 선택하세요</div>
			<div class="mt-1 text-xs text-muted-foreground">
				최대 {health?.max_files ?? 50}개, 파일당 {health?.max_per_file_mb ?? 25}MB
			</div>

			<label class="mt-4 inline-flex cursor-pointer items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
				파일 선택
				<input
					class="hidden"
					type="file"
					multiple
					accept="image/*,.heic,.heif"
					onchange={handleFileInput}
				/>
			</label>
		</div>

		<div class="mt-4 space-y-3">
			<label class="flex items-center gap-2 text-sm font-medium" for="image-pdf-bw">
				<input id="image-pdf-bw" type="checkbox" bind:checked={options.bw} />
				흑백 문서 보정
			</label>

			<div class="grid grid-cols-2 gap-3">
				<div>
					<label class="mb-1 block text-xs font-medium" for="image-pdf-white">흰색 임계값</label>
					<input
						id="image-pdf-white"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
						type="number"
						min="0"
						max="255"
						bind:value={options.white}
						disabled={!options.bw}
					/>
				</div>
				<div>
					<label class="mb-1 block text-xs font-medium" for="image-pdf-black">검정 임계값</label>
					<input
						id="image-pdf-black"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
						type="number"
						min="0"
						max="255"
						bind:value={options.black}
						disabled={!options.bw}
					/>
				</div>
			</div>

			<div>
				<label class="mb-1 block text-xs font-medium" for="image-pdf-quality">PDF 품질</label>
				<input
					id="image-pdf-quality"
					class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
					type="number"
					min="1"
					max="100"
					bind:value={options.quality}
				/>
			</div>

			<label class="flex items-center gap-2 text-sm font-medium" for="image-pdf-dpi">
				<input id="image-pdf-dpi" type="checkbox" bind:checked={options.preserveDpi} />
				원본 DPI 유지
			</label>

			<div>
				<label class="mb-1 block text-xs font-medium" for="image-pdf-output">출력 파일명</label>
				<input
					id="image-pdf-output"
					class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
					type="text"
					placeholder="image-pdf.pdf"
					bind:value={options.outputName}
				/>
			</div>
		</div>

		<button
			class="mt-4 inline-flex w-full items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
			onclick={handleSubmit}
			disabled={!canConvert}
		>
			{#if loading}
				<Loader2 size={16} class="mr-2 animate-spin" />
			{:else}
				<FileText size={16} class="mr-2" />
			{/if}
			PDF로 변환
		</button>
	</div>

	<div class="rounded-2xl border border-border bg-card p-5 shadow-sm">
		<div class="flex items-center justify-between gap-3">
			<div>
				<h2 class="text-base font-semibold">선택 파일</h2>
				<p class="mt-1 text-sm text-muted-foreground">
					현재 버전은 선택 순서를 그대로 PDF 페이지 순서로 사용합니다.
				</p>
			</div>
			{#if lastDownloadName}
				<div class="hidden items-center gap-1 rounded-full bg-success/10 px-3 py-1 text-xs font-medium text-success sm:flex">
					<Download size={13} />
					{lastDownloadName}
				</div>
			{/if}
		</div>

		{#if selectedFiles.length === 0}
			<div class="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
				아직 선택한 이미지가 없습니다.
			</div>
		{:else}
			<div class="mt-4 space-y-2">
				{#each selectedFiles as file, index (`${file.name}-${file.size}-${index}`)}
					<article class="flex items-center justify-between gap-3 rounded-xl border border-border px-3 py-2">
						<div class="min-w-0">
							<div class="truncate text-sm font-medium">{index + 1}. {file.name}</div>
							<div class="text-xs text-muted-foreground">{formatBytes(file.size)}</div>
						</div>
						<button
							type="button"
							class="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border text-muted-foreground hover:bg-muted/40 hover:text-destructive"
							aria-label={`${file.name} 제거`}
							onclick={() => removeFile(index)}
						>
							<Trash2 size={15} />
						</button>
					</article>
				{/each}
			</div>
		{/if}
	</div>
</section>
