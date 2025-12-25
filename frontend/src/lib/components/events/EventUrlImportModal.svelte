<script lang="ts">
	/**
	 * URL에서 이벤트 정보 추출 모달 컴포넌트
	 * - 즉시 추출: AI가 바로 이벤트 정보를 추출하여 편집 가능
	 * - 백그라운드 크롤링: 크롤링 큐에 등록 후 이력 페이지로 이동
	 */
	import { eventApi, crawlApi } from '$lib/api';
	import { toast } from '$lib/stores/toast';
	import type { EventImportFromUrlResponse, EventCreate } from '$lib/types';

	interface Props {
		show: boolean;
		onClose: () => void;
		onImportComplete: (eventData: EventCreate) => void;
	}

	let { show, onClose, onImportComplete }: Props = $props();

	// 모드 타입
	type ImportMode = 'instant' | 'background';

	// 상태
	let url = $state('');
	let loading = $state(false);
	let error: string | null = $state(null);
	let result: EventImportFromUrlResponse | null = $state(null);
	let mode: ImportMode = $state('instant');

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

	// URL 유효성 검사
	function isValidUrl(str: string): boolean {
		try {
			new URL(str);
			return true;
		} catch {
			return false;
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
			const response = await crawlApi.createRequest({
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
			if (message.includes('Instagram')) {
				toast.warning('Instagram URL은 Instagram 크롤러를 사용하세요.');
				handleClose();
				window.location.href = `/instagram/posts?shared_url=${encodeURIComponent(url.trim())}`;
			} else {
				error = message;
			}
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
		error = null;
		result = null;
		loading = false;
		mode = 'instant';
		onClose();
	}

	// 키보드 이벤트
	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			handleClose();
		} else if (e.key === 'Enter' && !loading && !result) {
			if (mode === 'instant') {
				handleExtract();
			} else {
				handleBackgroundCrawl();
			}
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
			class="bg-white rounded-t-xl sm:rounded-xl w-full sm:max-w-xl max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<!-- 헤더 -->
				<div class="flex justify-between items-start mb-4">
					<div>
						<h3 class="text-lg font-bold text-gray-900">URL에서 이벤트 가져오기</h3>
						<p class="text-sm text-gray-500 mt-1">
							이벤트 URL을 입력하면 AI가 정보를 추출합니다
						</p>
					</div>
					<button onclick={handleClose} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<!-- 모드 선택 -->
				<div class="mb-4 flex gap-2">
					<button
						onclick={() => { mode = 'instant'; result = null; error = null; }}
						class="flex-1 px-3 py-2 text-sm rounded-lg border transition-colors {mode === 'instant'
							? 'bg-blue-50 border-blue-500 text-blue-700'
							: 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'}"
					>
						<div class="font-medium">즉시 추출</div>
						<div class="text-xs opacity-75 mt-0.5">바로 편집 가능</div>
					</button>
					<button
						onclick={() => { mode = 'background'; result = null; error = null; }}
						class="flex-1 px-3 py-2 text-sm rounded-lg border transition-colors {mode === 'background'
							? 'bg-green-50 border-green-500 text-green-700'
							: 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'}"
					>
						<div class="font-medium">백그라운드 크롤링</div>
						<div class="text-xs opacity-75 mt-0.5">큐에 등록 후 이력 확인</div>
					</button>
				</div>

				<!-- URL 입력 -->
				<div class="space-y-4">
					<div>
						<label for="import-url" class="block text-sm font-medium text-gray-700 mb-1">
							이벤트 URL
						</label>
						<div class="flex gap-2">
							<input
								id="import-url"
								type="url"
								bind:value={url}
								placeholder="https://forms.gle/... 또는 https://naver.me/..."
								class="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
								disabled={loading}
							/>
							{#if mode === 'instant'}
								<button
									onclick={handleExtract}
									disabled={loading || !url.trim()}
									class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
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
									class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
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
						<p class="text-xs text-gray-500 mt-1">
							지원: Google Forms, Naver Form, Naver Blog, 일반 웹페이지
						</p>
					</div>

					<!-- 에러 메시지 -->
					{#if error}
						<div class="p-3 bg-red-50 border border-red-200 rounded-lg">
							<p class="text-sm text-red-700">{error}</p>
						</div>
					{/if}

					<!-- 추출 결과: 이벤트가 아닌 경우 (즉시 추출 모드에서만) -->
					{#if mode === 'instant' && result?.success && !result.is_event}
						<div class="p-4 bg-yellow-50 border border-yellow-200 rounded-lg space-y-3">
							<!-- 추출 정보 -->
							<div class="flex items-center gap-2 text-sm">
								<span class="px-2 py-0.5 bg-yellow-100 text-yellow-700 rounded-full text-xs">
									이벤트 아님
								</span>
								<span class="px-2 py-0.5 bg-gray-100 text-gray-700 rounded-full text-xs">
									{pageTypeLabels[result.page_type] || result.page_type}
								</span>
							</div>

							<!-- 분석 결과 -->
							<div class="space-y-2 text-sm">
								{#if result.extracted_event?.title}
									<div>
										<span class="font-medium text-gray-700">페이지 제목:</span>
										<span class="ml-2 text-gray-900">{result.extracted_event.title}</span>
									</div>
								{/if}

								<div>
									<span class="font-medium text-gray-700">분석 결과:</span>
									<p class="mt-1 text-yellow-700 text-sm bg-white p-2 rounded border border-yellow-200">
										{result.not_event_reason || '이 페이지는 이벤트/행사/프로모션 페이지가 아닙니다.'}
									</p>
								</div>

								{#if result.extracted_event?.summary}
									<div>
										<span class="font-medium text-gray-700">요약:</span>
										<p class="mt-1 text-gray-600 text-xs bg-white p-2 rounded border">
											{result.extracted_event.summary}
										</p>
									</div>
								{/if}
							</div>

							<!-- 액션 버튼 -->
							<div class="flex justify-end gap-2 pt-2 border-t border-yellow-200">
								<button
									onclick={handleClose}
									class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
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
						<div class="p-4 bg-green-50 border border-green-200 rounded-lg space-y-3">
							<!-- 추출 정보 -->
							<div class="flex items-center gap-2 text-sm">
								<span class="px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs">
									{pageTypeLabels[result.page_type] || result.page_type}
								</span>
								<span class="px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full text-xs">
									{extractionMethodLabels[result.extraction_method] || result.extraction_method}
								</span>
							</div>

							<!-- 추출된 이벤트 정보 -->
							<div class="space-y-2 text-sm">
								<div>
									<span class="font-medium text-gray-700">제목:</span>
									<span class="ml-2 text-gray-900">{result.extracted_event.title}</span>
								</div>

								{#if result.extracted_event.organizer}
									<div>
										<span class="font-medium text-gray-700">주최:</span>
										<span class="ml-2 text-gray-900">{result.extracted_event.organizer}</span>
									</div>
								{/if}

								{#if result.extracted_event.event_start || result.extracted_event.event_end}
									<div>
										<span class="font-medium text-gray-700">기간:</span>
										<span class="ml-2 text-gray-900">
											{result.extracted_event.event_start || '미정'} ~ {result.extracted_event.event_end || '미정'}
										</span>
									</div>
								{/if}

								{#if result.extracted_event.prizes && (result.extracted_event.prizes as string[]).length > 0}
									<div>
										<span class="font-medium text-gray-700">경품:</span>
										<span class="ml-2 text-gray-900">
											{(result.extracted_event.prizes as string[]).join(', ')}
										</span>
									</div>
								{/if}

								{#if result.extracted_event.winner_count}
									<div>
										<span class="font-medium text-gray-700">당첨자:</span>
										<span class="ml-2 text-gray-900">{result.extracted_event.winner_count}명</span>
									</div>
								{/if}

								{#if result.extracted_event.summary}
									<div>
										<span class="font-medium text-gray-700">요약:</span>
										<p class="mt-1 text-gray-600 text-xs bg-white p-2 rounded border">
											{result.extracted_event.summary}
										</p>
									</div>
								{/if}
							</div>

							<!-- 액션 버튼 -->
							<div class="flex justify-end gap-2 pt-2 border-t border-green-200">
								<button
									onclick={handleClose}
									class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800"
								>
									취소
								</button>
								<button
									onclick={handleUseExtractedData}
									class="px-4 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700"
								>
									이 정보로 이벤트 생성
								</button>
							</div>
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}
