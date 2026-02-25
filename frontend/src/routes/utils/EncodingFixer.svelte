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
	type Confidence = 'high' | 'medium' | 'low';

	interface DetectResult {
		encoding: Encoding;
		confidence: Confidence;
		candidates: Encoding[];
	}

	interface FileResult {
		name: string;
		rawBuf: ArrayBuffer;
		detectedEncoding: Encoding;
		confidence: Confidence;
		candidates: Encoding[];
		selectedEncoding: Encoding;
		originalPreview: string; // utf-8 강제 디코딩 (깨진 텍스트)
		convertedPreview: string; // selectedEncoding으로 디코딩 (복원)
		expanded: boolean;
		status: 'ok' | 'error';
		errorMsg?: string;
	}

	// ── 자동 감지 엔진 ──────────────────────────────────────────
	function detectEncoding(buf: ArrayBuffer): DetectResult {
		const bytes = new Uint8Array(buf);

		// 1. BOM 체크 (high confidence)
		if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
			return { encoding: 'utf-8', confidence: 'high', candidates: ['utf-8'] };
		}
		if (bytes[0] === 0xff && bytes[1] === 0xfe) {
			return { encoding: 'utf-16le', confidence: 'high', candidates: ['utf-16le'] };
		}
		if (bytes[0] === 0xfe && bytes[1] === 0xff) {
			return { encoding: 'utf-16be', confidence: 'high', candidates: ['utf-16be'] };
		}

		// 2. UTF-8 유효성 검사 (fatal 모드)
		let isValidUtf8 = false;
		let isAsciiOnly = true;
		try {
			new TextDecoder('utf-8', { fatal: true }).decode(buf);
			isValidUtf8 = true;
			// ASCII only 여부 확인
			for (let i = 0; i < Math.min(bytes.length, 2000); i++) {
				if (bytes[i] > 0x7f) { isAsciiOnly = false; break; }
			}
		} catch {
			isValidUtf8 = false;
		}

		// 3. EUC-KR 패턴 스캔 (0xA1~0xFE 연속 2바이트)
		let eucKrPairs = 0;
		const scanLen = Math.min(bytes.length, 4000);
		for (let i = 0; i < scanLen - 1; i++) {
			if (bytes[i] >= 0xa1 && bytes[i] <= 0xfe &&
				bytes[i + 1] >= 0xa1 && bytes[i + 1] <= 0xfe) {
				eucKrPairs++;
				i++; // 2바이트 소비
			}
		}
		const eucKrRatio = eucKrPairs / (scanLen / 2);

		// EUC-KR 유효성 추가 검증
		let isValidEucKr = false;
		try {
			new TextDecoder('euc-kr', { fatal: true }).decode(buf);
			isValidEucKr = true;
		} catch {
			isValidEucKr = false;
		}

		// 4. 판정
		if (!isValidUtf8) {
			// UTF-8 파싱 실패 → 멀티바이트 인코딩
			if (eucKrRatio > 0.05 && isValidEucKr) {
				return { encoding: 'euc-kr', confidence: 'medium', candidates: ['euc-kr', 'shift_jis', 'gbk'] };
			}
			if (isValidEucKr) {
				return { encoding: 'euc-kr', confidence: 'low', candidates: ['euc-kr', 'shift_jis', 'gbk', 'windows-1252'] };
			}
			return { encoding: 'euc-kr', confidence: 'low', candidates: ['euc-kr', 'shift_jis', 'gbk'] };
		}

		// UTF-8 유효
		if (isAsciiOnly) {
			// ASCII only: 판별 불가, EUC-KR 가능성도 있음
			return { encoding: 'utf-8', confidence: 'low', candidates: ['utf-8', 'euc-kr'] };
		}
		// 멀티바이트 UTF-8 확인됨
		return { encoding: 'utf-8', confidence: 'medium', candidates: ['utf-8'] };
	}

	function decodeText(buf: ArrayBuffer, encoding: Encoding): string {
		try {
			return new TextDecoder(encoding, { fatal: false }).decode(buf);
		} catch {
			return '(디코딩 실패)';
		}
	}

	function makePreview(text: string, expanded: boolean): string {
		const limit = expanded ? 3000 : 1000;
		return text.slice(0, limit);
	}

	// ── 상태 ────────────────────────────────────────────────────
	let autoDetect = $state(true);
	let globalEncoding: Encoding = $state('euc-kr');
	let results: FileResult[] = $state([]);
	let isDragging = $state(false);
	let processing = $state(false);
	let fileInput: HTMLInputElement;
	// 탭: 'original' | 'converted'
	let previewTab: Record<number, 'original' | 'converted'> = $state({});

	// ── 파일 처리 ───────────────────────────────────────────────
	function handleDrop(e: DragEvent) {
		e.preventDefault();
		isDragging = false;
		if (e.dataTransfer?.files) processFiles(e.dataTransfer.files);
	}

	function handleFileChange(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		if (input.files) processFiles(input.files);
	}

	async function processFiles(fileList: FileList) {
		processing = true;
		const newResults: FileResult[] = [];
		const newTabs: Record<number, 'original' | 'converted'> = {};

		for (const file of fileList) {
			try {
				const buf = await file.arrayBuffer();
				const detected = autoDetect ? detectEncoding(buf) : { encoding: globalEncoding, confidence: 'low' as Confidence, candidates: [globalEncoding] };
				const selectedEncoding = detected.encoding;

				// 원본 미리보기 (UTF-8 강제 → 깨진 텍스트)
				const originalPreview = decodeText(buf, 'utf-8');
				// 변환 미리보기 (감지/선택 인코딩)
				const convertedPreview = decodeText(buf, selectedEncoding);

				newResults.push({
					name: file.name,
					rawBuf: buf,
					detectedEncoding: detected.encoding,
					confidence: detected.confidence,
					candidates: detected.candidates,
					selectedEncoding,
					originalPreview,
					convertedPreview,
					expanded: false,
					status: 'ok',
				});
				newTabs[newResults.length - 1] = 'converted';
			} catch (err) {
				newResults.push({
					name: file.name,
					rawBuf: new ArrayBuffer(0),
					detectedEncoding: 'euc-kr',
					confidence: 'low',
					candidates: [],
					selectedEncoding: 'euc-kr',
					originalPreview: '',
					convertedPreview: '',
					expanded: false,
					status: 'error',
					errorMsg: String(err),
				});
			}
		}

		results = newResults;
		previewTab = newTabs;
		processing = false;
	}

	function changeEncoding(idx: number, enc: Encoding) {
		const r = results[idx];
		r.selectedEncoding = enc;
		r.convertedPreview = decodeText(r.rawBuf, enc);
		results = [...results];
	}

	function toggleExpand(idx: number) {
		results[idx].expanded = !results[idx].expanded;
		results = [...results];
	}

	function setTab(idx: number, tab: 'original' | 'converted') {
		previewTab = { ...previewTab, [idx]: tab };
	}

	// ── 다운로드 ─────────────────────────────────────────────────
	function downloadFile(result: FileResult) {
		const decoded = decodeText(result.rawBuf, result.selectedEncoding);
		const encoded = new TextEncoder().encode(decoded);
		const blob = new Blob([encoded], { type: 'text/plain;charset=utf-8' });
		const ext = result.name.match(/\.[^.]+$/)?.[0] ?? '';
		const base = result.name.replace(/\.[^.]+$/, '');
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${base}_utf8${ext}`;
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
		previewTab = {};
		if (fileInput) fileInput.value = '';
	}

	const CONFIDENCE_STYLE: Record<Confidence, string> = {
		high: 'bg-success/15 text-success border-success/30',
		medium: 'bg-warning/15 text-warning border-warning/30',
		low: 'bg-destructive/15 text-destructive border-destructive/30',
	};
	const CONFIDENCE_LABEL: Record<Confidence, string> = {
		high: '확실',
		medium: '추정',
		low: '불확실',
	};
</script>

<div class="bg-card border border-border rounded-xl p-6 space-y-5">
	<div>
		<h2 class="text-lg font-semibold">인코딩 변환기</h2>
		<p class="text-sm text-muted-foreground mt-1">
			인코딩이 깨진 파일을 UTF-8로 변환합니다. 자동 감지 또는 직접 인코딩을 선택하세요.
		</p>
	</div>

	<!-- 자동 감지 토글 + 글로벌 인코딩 선택 -->
	<div class="flex flex-wrap items-center gap-4">
		<label class="flex items-center gap-2 cursor-pointer select-none">
			<button
				role="switch"
				aria-checked={autoDetect}
				aria-label="인코딩 자동 감지 토글"
				onclick={() => (autoDetect = !autoDetect)}
				class="relative inline-flex w-10 h-5 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary
					{autoDetect ? 'bg-primary' : 'bg-muted'}"
			>
				<span
					class="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform
						{autoDetect ? 'translate-x-5' : 'translate-x-0'}"
				></span>
			</button>
			<span class="text-sm font-medium">인코딩 자동 감지</span>
		</label>

		{#if !autoDetect}
			<div class="flex-1 min-w-[220px]">
				<label class="block text-xs text-muted-foreground mb-1" for="global-enc">원본 인코딩 (전체 적용)</label>
				<select
					id="global-enc"
					bind:value={globalEncoding}
					class="w-full px-3 py-2 bg-input border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
				>
					{#each ENCODINGS as enc}
						<option value={enc.value}>{enc.label}</option>
					{/each}
				</select>
			</div>
		{/if}

		<div class="flex items-center gap-1.5 text-xs text-muted-foreground">
			<span>→</span>
			<span class="px-2 py-1 bg-muted/40 rounded">UTF-8 출력</span>
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
		<input bind:this={fileInput} type="file" multiple class="hidden" onchange={handleFileChange} />
	</div>

	<!-- 처리 중 -->
	{#if processing}
		<div class="flex items-center gap-2 text-sm text-muted-foreground">
			<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
			</svg>
			분석 중...
		</div>
	{/if}

	<!-- 결과 -->
	{#if results.length > 0}
		<div class="space-y-3">
			<div class="flex items-center justify-between">
				<h3 class="text-sm font-medium">결과 ({results.length}개 파일)</h3>
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

			{#each results as result, idx}
				<div class="border border-border rounded-lg overflow-hidden">
					<!-- 카드 헤더 -->
					<div class="flex flex-wrap items-center gap-3 px-4 py-2.5 bg-muted/30">
						<div class="flex items-center gap-2 flex-1 min-w-0">
							{#if result.status === 'ok'}
								<span class="text-success text-sm shrink-0">✓</span>
							{:else}
								<span class="text-destructive text-sm shrink-0">✗</span>
							{/if}
							<span class="text-sm font-medium truncate">{result.name}</span>
						</div>

						{#if result.status === 'ok'}
							<!-- 감지 배지 -->
							<div class="flex items-center gap-1.5 shrink-0">
								<span class="text-xs text-muted-foreground">감지:</span>
								<span class="px-2 py-0.5 text-xs border rounded {CONFIDENCE_STYLE[result.confidence]}">
									{result.detectedEncoding.toUpperCase()} · {CONFIDENCE_LABEL[result.confidence]}
								</span>
							</div>

							<!-- 파일별 인코딩 선택 -->
							<select
								value={result.selectedEncoding}
								onchange={(e) => changeEncoding(idx, (e.currentTarget as HTMLSelectElement).value as Encoding)}
								class="px-2 py-1 bg-input border border-border rounded text-xs focus:outline-none focus:ring-1 focus:ring-primary shrink-0"
								title="인코딩 변경 시 미리보기 즉시 갱신"
							>
								{#each ENCODINGS as enc}
									<option value={enc.value}>{enc.label}</option>
								{/each}
							</select>

							<button
								onclick={() => downloadFile(result)}
								class="px-3 py-1 bg-primary text-primary-foreground text-xs rounded-lg hover:bg-primary/90 transition-colors shrink-0"
							>
								다운로드
							</button>
						{/if}
					</div>

					<!-- 미리보기 -->
					{#if result.status === 'ok'}
						<div class="px-4 py-3">
							<!-- 탭 -->
							<div class="flex gap-1 mb-2">
								<button
									onclick={() => setTab(idx, 'converted')}
									class="px-3 py-1 text-xs rounded transition-colors
										{(previewTab[idx] ?? 'converted') === 'converted'
										? 'bg-primary text-primary-foreground'
										: 'text-muted-foreground hover:bg-muted/40'}"
								>
									변환 후 ({result.selectedEncoding.toUpperCase()} → UTF-8)
								</button>
								<button
									onclick={() => setTab(idx, 'original')}
									class="px-3 py-1 text-xs rounded transition-colors
										{(previewTab[idx] ?? 'converted') === 'original'
										? 'bg-muted text-foreground'
										: 'text-muted-foreground hover:bg-muted/40'}"
								>
									원본 (UTF-8 강제, 깨짐)
								</button>
							</div>

							<!-- 미리보기 텍스트 -->
							<pre class="text-xs bg-muted/20 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all
								{result.expanded ? 'max-h-96' : 'max-h-40'} overflow-y-auto"
							>{(previewTab[idx] ?? 'converted') === 'converted'
								? makePreview(result.convertedPreview, result.expanded)
								: makePreview(result.originalPreview, result.expanded)}</pre>

							<!-- 접기/펼치기 -->
							<button
								onclick={() => toggleExpand(idx)}
								class="mt-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
							>
								{result.expanded ? '▲ 접기' : '▼ 더 보기 (최대 3000자)'}
							</button>
						</div>
					{:else}
						<div class="px-4 py-3 text-xs text-destructive">{result.errorMsg}</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
