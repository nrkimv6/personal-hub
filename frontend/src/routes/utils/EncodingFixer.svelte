<script lang="ts">
	// 인코딩 감지 & 변환 유틸
	// 브라우저의 TextDecoder API를 사용해 EUC-KR / CP949 → UTF-8로 변환

	const ENCODINGS = [
		{ value: 'euc-kr', label: 'EUC-KR / CP949 (한국어)' },
		{ value: 'utf-8', label: 'UTF-8' },
		{ value: 'utf-16le', label: 'UTF-16 LE' },
		{ value: 'utf-16be', label: 'UTF-16 BE' },
		{ value: 'shift_jis', label: 'Shift_JIS (일본어)' },
		{ value: 'gbk', label: 'GBK (중국어 간체)' },
		{ value: 'big5', label: 'Big5 (중국어 번체)' },
		{ value: 'windows-1252', label: 'Windows-1252 (서유럽)' },
	] as const;

	type Encoding = (typeof ENCODINGS)[number]['value'];

	let files: FileList | null = $state(null);
	let fromEncoding: Encoding = $state('euc-kr');
	let toEncoding: Encoding = $state('utf-8');
	let results: { name: string; preview: string; blob: Blob; status: string }[] = $state([]);
	let isDragging = $state(false);
	let processing = $state(false);
	let fileInput: HTMLInputElement;

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		isDragging = false;
		if (e.dataTransfer?.files) {
			processFiles(e.dataTransfer.files);
		}
	}

	function handleFileChange(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		if (input.files) processFiles(input.files);
	}

	async function processFiles(fileList: FileList) {
		processing = true;
		results = [];
		const newResults: typeof results = [];

		for (const file of fileList) {
			try {
				const buf = await file.arrayBuffer();

				// 지정 인코딩으로 디코딩
				const decoder = new TextDecoder(fromEncoding, { fatal: false });
				const decoded = decoder.decode(buf);

				// UTF-8로 재인코딩 (Blob)
				const encoder = new TextEncoder(); // 항상 UTF-8
				const encoded = encoder.encode(decoded);
				const blob = new Blob([encoded], { type: 'text/plain;charset=utf-8' });

				// 미리보기 (앞 500자)
				const preview = decoded.slice(0, 500);

				newResults.push({ name: file.name, preview, blob, status: 'ok' });
			} catch (err) {
				newResults.push({
					name: file.name,
					preview: `변환 실패: ${err}`,
					blob: new Blob(),
					status: 'error'
				});
			}
		}

		results = newResults;
		processing = false;
	}

	function downloadFile(result: (typeof results)[number]) {
		const ext = result.name.match(/\.[^.]+$/)?.[0] ?? '';
		const base = result.name.replace(/\.[^.]+$/, '');
		const newName = `${base}_utf8${ext}`;
		const url = URL.createObjectURL(result.blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = newName;
		a.click();
		URL.revokeObjectURL(url);
	}

	function downloadAll() {
		for (const r of results) {
			if (r.status === 'ok') downloadFile(r);
		}
	}

	function reset() {
		results = [];
		files = null;
		if (fileInput) fileInput.value = '';
	}
</script>

<div class="bg-card border border-border rounded-xl p-6 space-y-5">
	<div>
		<h2 class="text-lg font-semibold">인코딩 변환기</h2>
		<p class="text-sm text-muted-foreground mt-1">
			인코딩이 깨진 파일을 UTF-8로 변환합니다. 여러 파일을 한번에 처리할 수 있습니다.
		</p>
	</div>

	<!-- 인코딩 선택 -->
	<div class="flex flex-wrap gap-4">
		<div class="flex-1 min-w-[200px]">
			<label class="block text-sm font-medium mb-1" for="from-enc">원본 인코딩</label>
			<select
				id="from-enc"
				bind:value={fromEncoding}
				class="w-full px-3 py-2 bg-input border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
			>
				{#each ENCODINGS as enc}
					<option value={enc.value}>{enc.label}</option>
				{/each}
			</select>
		</div>

		<div class="flex items-end pb-1 text-muted-foreground">→</div>

		<div class="flex-1 min-w-[200px]">
			<label class="block text-sm font-medium mb-1" for="to-enc">변환 인코딩</label>
			<select
				id="to-enc"
				class="w-full px-3 py-2 bg-input border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary opacity-60 cursor-not-allowed"
				disabled
			>
				<option>UTF-8 (항상)</option>
			</select>
			<p class="text-xs text-muted-foreground mt-1">출력은 항상 UTF-8</p>
		</div>
	</div>

	<!-- 드래그&드롭 영역 -->
	<div
		role="region"
		aria-label="파일 드롭 영역"
		class="border-2 border-dashed rounded-xl p-10 text-center transition-colors
			{isDragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'}"
		ondragover={(e) => { e.preventDefault(); isDragging = true; }}
		ondragleave={() => { isDragging = false; }}
		ondrop={handleDrop}
	>
		<div class="text-4xl mb-3">📄</div>
		<p class="text-sm text-muted-foreground mb-3">
			파일을 여기에 드래그하거나 클릭해서 선택하세요
		</p>
		<button
			onclick={() => fileInput.click()}
			class="px-4 py-2 bg-primary text-primary-foreground text-sm rounded-lg hover:bg-primary/90 transition-colors"
		>
			파일 선택
		</button>
		<input
			bind:this={fileInput}
			type="file"
			multiple
			class="hidden"
			onchange={handleFileChange}
		/>
	</div>

	<!-- 처리 중 -->
	{#if processing}
		<div class="flex items-center gap-2 text-sm text-muted-foreground">
			<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
			</svg>
			변환 중...
		</div>
	{/if}

	<!-- 결과 -->
	{#if results.length > 0}
		<div class="space-y-3">
			<div class="flex items-center justify-between">
				<h3 class="text-sm font-medium">변환 결과 ({results.length}개)</h3>
				<div class="flex gap-2">
					<button
						onclick={downloadAll}
						class="px-3 py-1.5 bg-success text-success-foreground text-sm rounded-lg hover:bg-success/90 transition-colors"
					>
						모두 다운로드
					</button>
					<button
						onclick={reset}
						class="px-3 py-1.5 bg-secondary text-secondary-foreground text-sm rounded-lg hover:bg-secondary/80 transition-colors"
					>
						초기화
					</button>
				</div>
			</div>

			{#each results as result}
				<div class="border border-border rounded-lg overflow-hidden">
					<div class="flex items-center justify-between px-4 py-2 bg-muted/30">
						<div class="flex items-center gap-2">
							{#if result.status === 'ok'}
								<span class="text-success text-sm">✓</span>
							{:else}
								<span class="text-destructive text-sm">✗</span>
							{/if}
							<span class="text-sm font-medium">{result.name}</span>
						</div>
						{#if result.status === 'ok'}
							<button
								onclick={() => downloadFile(result)}
								class="px-3 py-1 bg-primary text-primary-foreground text-xs rounded-lg hover:bg-primary/90 transition-colors"
							>
								다운로드
							</button>
						{/if}
					</div>
					<div class="px-4 py-3">
						<p class="text-xs text-muted-foreground mb-1">미리보기 (앞 500자)</p>
						<pre class="text-xs bg-muted/20 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all max-h-40 overflow-y-auto">{result.preview}</pre>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
