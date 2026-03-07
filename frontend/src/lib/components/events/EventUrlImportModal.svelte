<script lang="ts">
	/**
	 * URL에서 이벤트 정보 추출 모달 컴포넌트
	 * - 배치 크롤링: 다건 URL 배치 크롤링 (모든 URL 타입 지원)
	 * - 즉시 추출: AI가 바로 이벤트 정보를 추출하여 편집 가능
	 * - 백그라운드 크롤링: 크롤링 큐에 등록 후 이력 페이지로 이동
	 */
	import { eventApi, crawlApi, collectApi } from '$lib/api';
	import { toast } from '$lib/stores/toast';
	import type { EventImportFromUrlResponse, EventCreate, ServiceAccountWithProfile } from '$lib/types';

	interface Props {
		show: boolean;
		onClose: () => void;
		onImportComplete: (eventData: EventCreate) => void;
	}

	let { show, onClose, onImportComplete }: Props = $props();

	// 모드 타입: 배치 크롤링을 첫 번째로
	type ImportMode = 'batch' | 'instant' | 'background';

	// 상태
	let url = $state('');
	let urlsInput = $state('');  // 다건 URL 입력
	let loading = $state(false);
	let error: string | null = $state(null);
	let result: EventImportFromUrlResponse | null = $state(null);
	let mode: ImportMode = $state('batch');  // 기본값: 배치 크롤링

	// Instagram 계정 (Instagram URL에만 필요)
	let accounts: ServiceAccountWithProfile[] = $state([]);
	let selectedAccountId: number | null = $state(null);
	let crawlResult: { created: number; skipped: number; errors: string[]; request_ids?: number[] } | null = $state(null);

	// URL 파싱 (모든 URL 지원)
	const parsedUrls = $derived(
		urlsInput
			.split('\n')
			.map(line => line.trim())
			.filter(line => {
				if (!line) return false;
				try {
					new URL(line);
					return true;
				} catch {
					return false;
				}
			})
	);

	// Instagram URL 개수
	const instagramUrlCount = $derived(
		parsedUrls.filter(url => url.includes('instagram.com') || url.includes('instagr.am')).length
	);

	// 페이지 타입 라벨
	const pageTypeLabels: Record<string, string> = {
		google_forms: 'Google Forms',
		naver_form: 'Naver Form',
		naver_blog_pc: 'Naver Blog (PC)',
		naver_blog_mobile: 'Naver Blog (Mobile)',
		generic: '일반 웹페이지'
	};

	// 추출 방법 라벨
	const extractionMethodLabels: Record<string, string> = {
		structured: '구조화 추출',
		generic: '범용 추출',
		fallback: '폴백 추출',
		failed: '추출 실패'
	};

	// 계정 목록 로드 (Instagram URL 크롤링용)
	async function loadAccounts() {
		try {
			accounts = await collectApi.getAccounts();
			// 첫 번째 계정 자동 선택
			if (accounts.length > 0 && !selectedAccountId) {
				selectedAccountId = accounts[0].id;
			}
		} catch (e) {
			console.error('계정 목록 로드 실패:', e);
		}
	}

	// Instagram URL이 있을 때만 계정 로드
	$effect(() => {
		if (show && instagramUrlCount > 0 && accounts.length === 0) {
			loadAccounts();
		}
	});

	// URL 유효성 검사
	function isValidUrl(str: string): boolean {
		try {
			new URL(str);
			return true;
		} catch {
			return false;
		}
	}

	// 배치 크롤링 요청 (모든 URL 타입 지원)
	async function handleBatchCrawl() {
		if (parsedUrls.length === 0) {
			error = 'URL을 입력해주세요.';
			return;
		}

		// Instagram URL이 있는데 계정이 선택되지 않은 경우
		if (instagramUrlCount > 0 && !selectedAccountId) {
			error = 'Instagram URL이 있습니다. 수집 계정을 선택해주세요.';
			return;
		}

		loading = true;
		error = null;
		crawlResult = null;

		try {
			crawlResult = await collectApi.crawlByUrls(parsedUrls, {
				serviceAccountId: selectedAccountId ?? undefined
			});

			if (crawlResult.created > 0) {
				toast.success(`${crawlResult.created}개 크롤링 요청 등록 완료`);
			}
			if (crawlResult.skipped > 0) {
				toast.warning(`${crawlResult.skipped}개 스킵됨`);
			}
		} catch (e) {
			const message = e instanceof Error ? e.message : '알 수 없는 오류';
			error = message;
		} finally {
			loading = false;
		}
	}

	// 백그라운드 크롤링 요청
	async function handleBackgroundCrawl() {
		if (!url.trim()) {
			error = 'URL을 입력해주세요.';
			return;
		}

		if (!isValidUrl(url.trim())) {
			error = '유효한 URL을 입력해주세요.';
			return;
		}

		loading = true;
		error = null;

		try {
			const response = await crawlApi.createUrlRequest({
				url: url.trim(),
				auto_analyze: true,
				priority: 0
			});

			if (response.success) {
				toast.success(`크롤링 요청 등록 완료 (${response.url_type})`);
				handleClose();
				// 크롤링 이력 페이지로 이동
				window.location.href = '/crawl';
			}
		} catch (e) {
			const message = e instanceof Error ? e.message : '알 수 없는 오류';
			error = message;
		} finally {
			loading = false;
		}
	}

	// URL에서 이벤트 추출
	async function handleExtract() {
		if (!url.trim()) {
			error = 'URL을 입력해주세요.';
			return;
		}

		if (!isValidUrl(url.trim())) {
			error = '유효한 URL을 입력해주세요.';
			return;
		}

		loading = true;
		error = null;
		result = null;

		try {
			result = await eventApi.importFromUrl(url.trim(), false);

			if (!result.success) {
				error = result.error || '이벤트 정보 추출에 실패했습니다.';
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '알 수 없는 오류가 발생했습니다.';
		} finally {
			loading = false;
		}
	}

	// 추출된 데이터로 이벤트 생성 폼 열기
	function handleUseExtractedData() {
		if (!result?.extracted_event) return;

		const eventData: EventCreate = {
			title: (result.extracted_event.title as string) || '',
			event_type: (result.extracted_event.event_type as 'event' | 'popup' | 'ambassador' | 'other') || 'event',
			event_url: url.trim(),
			event_start: result.extracted_event.event_start as string | undefined,
			event_end: result.extracted_event.event_end as string | undefined,
			announcement_date: result.extracted_event.announcement_date as string | undefined,
			organizer: result.extracted_event.organizer as string | undefined,
			summary: result.extracted_event.summary as string | undefined,
			prizes: (result.extracted_event.prizes as string[]) || [],
			winner_count: result.extracted_event.winner_count as number | undefined,
			purchase_required: result.extracted_event.purchase_required as string | undefined,
			location_venue: result.extracted_event.location_venue as string | undefined,
			location_address: result.extracted_event.location_address as string | undefined,
			source_type: 'web',
			source_url: url.trim(),
			input_source: 'ai'
		};

		onImportComplete(eventData);
		handleClose();
	}

	// 모달 닫기
	function handleClose() {
		url = '';
		urlsInput = '';
		error = null;
		result = null;
		crawlResult = null;
		loading = false;
		mode = 'batch';
		onClose();
	}

	// 모드 변경
	function switchMode(newMode: ImportMode) {
		mode = newMode;
		result = null;
		crawlResult = null;
		error = null;
	}

	// 키보드 이벤트
	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			handleClose();
		}
	}
</script>

{#if show}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4"
		onclick={handleClose}
		onkeydown={handleKeydown}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="bg-white rounded-t-xl sm:rounded-xl w-full sm:max-w-xl max-h-[90dvh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<!-- 헤더 -->
				<div class="flex justify-between items-start mb-4">
					<div>
						<h3 class="text-lg font-bold text-foreground">URL에서 가져오기</h3>
						<p class="text-sm text-muted-foreground mt-1">
							{#if mode === 'batch'}
								URL을 입력하면 크롤링 큐에 등록됩니다
							{:else if mode === 'instant'}
								이벤트 URL을 입력하면 AI가 정보를 추출합니다
							{:else}
								URL을 크롤링 큐에 등록합니다
							{/if}
						</p>
					</div>
					<button onclick={handleClose} class="text-muted-foreground hover:text-muted-foreground text-2xl">
						&times;
					</button>
				</div>

				<!-- 모드 선택 -->
				<div class="mb-4 flex gap-2">
					<button
						onclick={() => switchMode('batch')}
						class="flex-1 px-3 py-2 text-sm rounded-lg border transition-colors {mode === 'batch'
							? 'bg-purple-light border-purple-500 text-purple'
							: 'bg-card border-border text-muted-foreground hover:bg-muted'}"
					>
						<div class="font-medium">배치 크롤링</div>
						<div class="text-xs opacity-75 mt-0.5">다건 URL 지원</div>
					</button>
					<button
						onclick={() => switchMode('instant')}
						class="flex-1 px-3 py-2 text-sm rounded-lg border transition-colors {mode === 'instant'
							? 'bg-primary-light border-blue-500 text-primary'
							: 'bg-card border-border text-muted-foreground hover:bg-muted'}"
					>
						<div class="font-medium">이벤트 추출</div>
						<div class="text-xs opacity-75 mt-0.5">AI로 정보 추출</div>
					</button>
					<button
						onclick={() => switchMode('background')}
						class="flex-1 px-3 py-2 text-sm rounded-lg border transition-colors {mode === 'background'
							? 'bg-success-light border-green-500 text-success'
							: 'bg-card border-border text-muted-foreground hover:bg-muted'}"
					>
						<div class="font-medium">백그라운드</div>
						<div class="text-xs opacity-75 mt-0.5">큐에 등록</div>
					</button>
				</div>

				<!-- 배치 크롤링 모드 -->
				{#if mode === 'batch'}
					<div class="space-y-4">
						<!-- URL 입력 (다건) -->
						<div>
							<label for="urls-input" class="block text-sm font-medium text-foreground mb-1">
								URL (한 줄에 하나씩)
							</label>
							<textarea
								id="urls-input"
								bind:value={urlsInput}
								placeholder="https://www.instagram.com/p/xxx/&#10;https://forms.gle/xxx&#10;https://blog.naver.com/xxx/xxx"
								rows="5"
								class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-purple-500 font-mono text-sm"
								disabled={loading}
							></textarea>
							<div class="flex justify-between items-center mt-1">
								<p class="text-xs text-muted-foreground">
									Instagram, Google Forms, Naver Blog 등 (최대 20개)
								</p>
								<span class="text-xs font-medium {parsedUrls.length > 0 ? 'text-purple' : 'text-muted-foreground'}">
									{parsedUrls.length}개 URL
									{#if instagramUrlCount > 0}
										<span class="text-pink-500">(IG: {instagramUrlCount})</span>
									{/if}
								</span>
							</div>
						</div>

						<!-- Instagram URL이 있을 때만 계정 선택 표시 -->
						{#if instagramUrlCount > 0}
							<div>
								<label for="account-select" class="block text-sm font-medium text-foreground mb-1">
									Instagram 수집 계정
								</label>
								<select
									id="account-select"
									bind:value={selectedAccountId}
									class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-pink-500 focus:border-pink-500"
									disabled={loading}
								>
									{#if accounts.length === 0}
										<option value={null}>계정 로딩 중...</option>
									{:else}
										{#each accounts as account}
											<option value={account.id}>
												{account.username} ({account.profile_name})
											</option>
										{/each}
									{/if}
								</select>
								<p class="text-xs text-pink-500 mt-1">
									Instagram URL 크롤링에 필요합니다
								</p>
							</div>
						{/if}

						<!-- 크롤링 버튼 -->
						<button
							onclick={handleBatchCrawl}
							disabled={loading || parsedUrls.length === 0 || (instagramUrlCount > 0 && !selectedAccountId)}
							class="w-full px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center justify-center gap-2"
						>
							{#if loading}
								<span class="animate-spin">⏳</span>
								등록 중...
							{:else}
								크롤링 요청 ({parsedUrls.length}개)
							{/if}
						</button>

						<!-- 크롤링 결과 -->
						{#if crawlResult}
							<div class="p-4 bg-background border border-border rounded-lg space-y-2">
								<div class="flex items-center gap-4 text-sm">
									<span class="text-success font-medium">등록: {crawlResult.created}개</span>
									{#if crawlResult.skipped > 0}
										<span class="text-warning-foreground">스킵: {crawlResult.skipped}개</span>
									{/if}
								</div>
								{#if crawlResult.errors.length > 0}
									<div class="mt-2">
										<p class="text-xs font-medium text-muted-foreground mb-1">상세:</p>
										<ul class="text-xs text-muted-foreground space-y-0.5 max-h-24 overflow-y-auto">
											{#each crawlResult.errors as err}
												<li class="truncate" title={err}>• {err}</li>
											{/each}
										</ul>
									</div>
								{/if}
								<div class="pt-2 border-t border-border">
									<a href="/crawl" class="text-sm text-purple hover:text-purple">
										크롤링 이력 확인 →
									</a>
								</div>
							</div>
						{/if}
					</div>
				{/if}

				<!-- 이벤트 추출 / 백그라운드 모드 -->
				{#if mode === 'instant' || mode === 'background'}
					<div class="space-y-4">
						<div>
							<label for="import-url" class="block text-sm font-medium text-foreground mb-1">
								{mode === 'instant' ? '이벤트 URL' : 'URL'}
							</label>
							<div class="flex gap-2">
								<input
									id="import-url"
									type="url"
									bind:value={url}
									placeholder="https://forms.gle/... 또는 https://naver.me/..."
									class="flex-1 px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
									disabled={loading}
								/>
								{#if mode === 'instant'}
									<button
										onclick={handleExtract}
										disabled={loading || !url.trim()}
										class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
									>
										{#if loading}
											<span class="animate-spin">⏳</span>
											추출 중...
										{:else}
											추출
										{/if}
									</button>
								{:else}
									<button
										onclick={handleBackgroundCrawl}
										disabled={loading || !url.trim()}
										class="px-4 py-2 bg-success text-white rounded-lg hover:bg-success/90 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
									>
										{#if loading}
											<span class="animate-spin">⏳</span>
											등록 중...
										{:else}
											큐에 등록
										{/if}
									</button>
								{/if}
							</div>
							<p class="text-xs text-muted-foreground mt-1">
								지원: Google Forms, Naver Form, Naver Blog, Instagram, 일반 웹페이지
							</p>
						</div>

						<!-- 에러 메시지 -->
						{#if error}
							<div class="p-3 bg-error-light border border-red-200 rounded-lg">
								<p class="text-sm text-error">{error}</p>
							</div>
						{/if}

						<!-- 추출 결과: 이벤트가 아닌 경우 (즉시 추출 모드에서만) -->
						{#if mode === 'instant' && result?.success && !result.is_event}
							<div class="p-4 bg-warning-light border border-yellow-200 rounded-lg space-y-3">
								<!-- 추출 정보 -->
								<div class="flex items-center gap-2 text-sm">
									<span class="px-2 py-0.5 bg-warning-light text-warning-foreground rounded-full text-xs">
										이벤트 아님
									</span>
									<span class="px-2 py-0.5 bg-muted text-foreground rounded-full text-xs">
										{pageTypeLabels[result.page_type] || result.page_type}
									</span>
								</div>

								<!-- 분석 결과 -->
								<div class="space-y-2 text-sm">
									{#if result.extracted_event?.title}
										<div>
											<span class="font-medium text-foreground">페이지 제목:</span>
											<span class="ml-2 text-foreground">{result.extracted_event.title}</span>
										</div>
									{/if}

									<div>
										<span class="font-medium text-foreground">분석 결과:</span>
										<p class="mt-1 text-warning-foreground text-sm bg-white p-2 rounded border border-yellow-200">
											{result.not_event_reason || '이 페이지는 이벤트/행사/프로모션 페이지가 아닙니다.'}
										</p>
									</div>

									{#if result.extracted_event?.summary}
										<div>
											<span class="font-medium text-foreground">요약:</span>
											<p class="mt-1 text-muted-foreground text-xs bg-white p-2 rounded border">
												{result.extracted_event.summary}
											</p>
										</div>
									{/if}
								</div>

								<!-- 액션 버튼 -->
								<div class="flex justify-end gap-2 pt-2 border-t border-yellow-200">
									<button
										onclick={handleClose}
										class="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
									>
										닫기
									</button>
									<button
										onclick={handleUseExtractedData}
										class="px-4 py-1.5 text-sm bg-yellow-600 text-white rounded-lg hover:bg-yellow-700"
									>
										그래도 이벤트로 등록
									</button>
								</div>
							</div>
						{/if}

						<!-- 추출 결과: 이벤트인 경우 (즉시 추출 모드에서만) -->
						{#if mode === 'instant' && result?.success && result.is_event && result.extracted_event}
							<div class="p-4 bg-success-light border border-green-200 rounded-lg space-y-3">
								<!-- 추출 정보 -->
								<div class="flex items-center gap-2 text-sm">
									<span class="px-2 py-0.5 bg-success-light text-success rounded-full text-xs">
										{pageTypeLabels[result.page_type] || result.page_type}
									</span>
									<span class="px-2 py-0.5 bg-primary-light text-primary rounded-full text-xs">
										{extractionMethodLabels[result.extraction_method] || result.extraction_method}
									</span>
								</div>

								<!-- 추출된 이벤트 정보 -->
								<div class="space-y-2 text-sm">
									<div>
										<span class="font-medium text-foreground">제목:</span>
										<span class="ml-2 text-foreground">{result.extracted_event.title}</span>
									</div>

									{#if result.extracted_event.organizer}
										<div>
											<span class="font-medium text-foreground">주최:</span>
											<span class="ml-2 text-foreground">{result.extracted_event.organizer}</span>
										</div>
									{/if}

									{#if result.extracted_event.event_start || result.extracted_event.event_end}
										<div>
											<span class="font-medium text-foreground">기간:</span>
											<span class="ml-2 text-foreground">
												{result.extracted_event.event_start || '미정'} ~ {result.extracted_event.event_end || '미정'}
											</span>
										</div>
									{/if}

									{#if result.extracted_event.prizes && (result.extracted_event.prizes as string[]).length > 0}
										<div>
											<span class="font-medium text-foreground">경품:</span>
											<span class="ml-2 text-foreground">
												{(result.extracted_event.prizes as string[]).join(', ')}
											</span>
										</div>
									{/if}

									{#if result.extracted_event.winner_count}
										<div>
											<span class="font-medium text-foreground">당첨자:</span>
											<span class="ml-2 text-foreground">{result.extracted_event.winner_count}명</span>
										</div>
									{/if}

									{#if result.extracted_event.summary}
										<div>
											<span class="font-medium text-foreground">요약:</span>
											<p class="mt-1 text-muted-foreground text-xs bg-white p-2 rounded border">
												{result.extracted_event.summary}
											</p>
										</div>
									{/if}
								</div>

								<!-- 액션 버튼 -->
								<div class="flex justify-end gap-2 pt-2 border-t border-green-200">
									<button
										onclick={handleClose}
										class="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
									>
										취소
									</button>
									<button
										onclick={handleUseExtractedData}
										class="px-4 py-1.5 text-sm bg-success text-white rounded-lg hover:bg-success/90"
									>
										이 정보로 이벤트 생성
									</button>
								</div>
							</div>
						{/if}
					</div>
				{/if}

				<!-- 배치 모드에서 에러 메시지 -->
				{#if mode === 'batch' && error}
					<div class="mt-4 p-3 bg-error-light border border-red-200 rounded-lg">
						<p class="text-sm text-error">{error}</p>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
