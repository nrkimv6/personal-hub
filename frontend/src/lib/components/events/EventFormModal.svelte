<script lang="ts">
	/**
	 * 이벤트 생성/수정 모달 컴포넌트
	 */
	import type { Event, EventCreate, EventUpdate } from '$lib/types';
	import { prizesToText, textToPrizes } from '$lib/utils/eventUtils';

	interface Props {
		show: boolean;
		editingEvent: Event | null;
		importedData?: EventCreate | null;  // URL 가져오기로 추출된 데이터
		activeTab?: 'event' | 'popup';
		onClose: () => void;
		onSave: (data: EventCreate | EventUpdate, isEdit: boolean) => Promise<void>;
	}

	let { show, editingEvent, importedData = null, activeTab = 'event', onClose, onSave }: Props = $props();

	// 폼 상태
	let eventForm: EventCreate = $state({
		title: '',
		event_type: 'event'
	});
	let prizesText = $state('');
	let isSaving = $state(false);

	// 복수 URL 관리
	let eventUrls = $state<string[]>(['']);

	// URL 배열 → event_url + additional_urls 변환
	function urlsToFormData(urls: string[]): { event_url: string | null; additional_urls: string[] } {
		const filtered = urls.filter(u => u.trim());
		return {
			event_url: filtered[0] || null,
			additional_urls: filtered.slice(1)
		};
	}

	// event_url + additional_urls → URL 배열 변환
	function formDataToUrls(eventUrl: string | null, additionalUrls: string[] | undefined): string[] {
		const urls: string[] = [];
		if (eventUrl) urls.push(eventUrl);
		if (additionalUrls?.length) urls.push(...additionalUrls);
		return urls.length ? urls : [''];  // 최소 1개 빈 입력
	}

	// URL 추가
	function addUrl() {
		eventUrls = [...eventUrls, ''];
	}

	// URL 삭제
	function removeUrl(index: number) {
		if (eventUrls.length > 1) {
			eventUrls = eventUrls.filter((_, i) => i !== index);
		}
	}

	// editingEvent 또는 importedData가 변경되면 폼 초기화
	$effect(() => {
		if (show) {
			if (editingEvent) {
				// 수정 모드: 기존 이벤트 데이터로 초기화
				eventForm = {
					title: editingEvent.title,
					event_type: editingEvent.event_type,
					status: editingEvent.status,
					event_start: editingEvent.event_start || '',
					event_end: editingEvent.event_end || '',
					organizer: editingEvent.organizer || '',
					summary: editingEvent.summary || '',
					location_venue: editingEvent.location_venue || '',
					location_address: editingEvent.location_address || '',
					announcement_date: editingEvent.announcement_date || '',
					prizes: editingEvent.prizes || [],
					winner_count: editingEvent.winner_count,
					purchase_required: editingEvent.purchase_required,
					user_note: editingEvent.user_note || '',
					body_text: editingEvent.body_text || ''
				};
				prizesText = prizesToText(editingEvent.prizes);
				eventUrls = formDataToUrls(editingEvent.event_url, editingEvent.additional_urls);
			} else if (importedData) {
				// URL 가져오기 모드: 추출된 데이터로 초기화
				eventForm = {
					title: importedData.title || '',
					event_type: importedData.event_type || 'event',
					event_start: importedData.event_start || '',
					event_end: importedData.event_end || '',
					organizer: importedData.organizer || '',
					summary: importedData.summary || '',
					location_venue: importedData.location_venue || '',
					location_address: importedData.location_address || '',
					announcement_date: importedData.announcement_date || '',
					prizes: importedData.prizes || [],
					winner_count: importedData.winner_count,
					purchase_required: importedData.purchase_required,
					source_type: importedData.source_type,
					source_url: importedData.source_url,
					input_source: importedData.input_source,
					body_text: importedData.body_text || ''
				};
				prizesText = prizesToText(importedData.prizes);
				eventUrls = formDataToUrls(importedData.event_url, importedData.additional_urls);
			} else {
				// 새 이벤트 모드: 빈 폼으로 초기화
				eventForm = {
					title: '',
					event_type: activeTab === 'popup' ? 'popup' : 'event',
					event_start: '',
					event_end: '',
					organizer: '',
					summary: '',
					location_venue: '',
					location_address: '',
					announcement_date: '',
					prizes: [],
					winner_count: undefined,
					purchase_required: undefined
				};
				prizesText = '';
				eventUrls = [''];
			}
		}
	});

	async function handleSave() {
		if (!eventForm.title.trim()) {
			alert('제목을 입력해주세요.');
			return;
		}
		isSaving = true;
		try {
			// URL 배열 → event_url + additional_urls 변환
			const { event_url, additional_urls } = urlsToFormData(eventUrls);

			// 빈 문자열을 null로 변환 (날짜 및 선택 필드)
			const formData = {
				...eventForm,
				prizes: textToPrizes(prizesText),
				event_start: eventForm.event_start || null,
				event_end: eventForm.event_end || null,
				announcement_date: eventForm.announcement_date || null,
				event_url,
				additional_urls,
				organizer: eventForm.organizer || null,
				summary: eventForm.summary || null,
				location_venue: eventForm.location_venue || null,
				location_address: eventForm.location_address || null,
				user_note: eventForm.user_note || null,
				purchase_required: eventForm.purchase_required || null,
				body_text: eventForm.body_text || null
			};
			await onSave(formData, !!editingEvent);
			onClose();
		} catch (e) {
			alert('저장 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			isSaving = false;
		}
	}
</script>

{#if show}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4"
		onclick={onClose}
		onkeydown={(e) => e.key === 'Escape' && onClose()}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="bg-white rounded-t-xl sm:rounded-xl w-full sm:max-w-2xl max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<div class="flex items-center gap-2">
						<h3 class="text-lg font-bold text-gray-900">
							{editingEvent ? '이벤트 수정' : importedData ? 'URL에서 가져온 이벤트' : '새 이벤트'}
						</h3>
						{#if editingEvent}
							{@const inputSource = editingEvent.input_source || 'human'}
							<span
								class="px-2 py-0.5 text-xs rounded-full {inputSource === 'ai'
									? 'bg-purple-100 text-purple-700'
									: inputSource === 'ai_edited'
										? 'bg-blue-100 text-blue-700'
										: 'bg-gray-100 text-gray-600'}"
							>
								{inputSource === 'ai' ? 'AI 분석' : inputSource === 'ai_edited' ? 'AI+수정' : '수동 입력'}
							</span>
						{:else if importedData}
							<span class="px-2 py-0.5 text-xs rounded-full bg-purple-100 text-purple-700">
								AI 분석
							</span>
						{/if}
					</div>
					<button onclick={onClose} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="space-y-4">
					<!-- 제목 -->
					<div>
						<label for="event-title" class="block text-sm font-medium text-gray-700 mb-1">
							제목 <span class="text-red-500">*</span>
						</label>
						<input
							id="event-title"
							type="text"
							bind:value={eventForm.title}
							placeholder="이벤트 제목"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>
					</div>

					<!-- 유형 + 상태 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-type" class="block text-sm font-medium text-gray-700 mb-1"
								>유형</label
							>
							<select
								id="event-type"
								bind:value={eventForm.event_type}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							>
								<option value="event">이벤트</option>
								<option value="popup">팝업</option>
								<option value="ambassador">홍보대사</option>
								<option value="other">기타</option>
							</select>
						</div>
						{#if editingEvent}
							<div>
								<label for="event-status" class="block text-sm font-medium text-gray-700 mb-1"
									>상태</label
								>
								<select
									id="event-status"
									bind:value={eventForm.status}
									class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
								>
									<option value="active">활성</option>
									<option value="ended">종료</option>
									<option value="cancelled">취소</option>
								</select>
							</div>
						{/if}
					</div>

					<!-- 이벤트 URL 목록 -->
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">이벤트 URL</label>
						<div class="space-y-2">
							{#each eventUrls as url, index}
								<div class="flex gap-2 items-center">
									<input
										type="text"
										bind:value={eventUrls[index]}
										placeholder="https://..."
										class="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
									/>
									{#if index === 0}
										<span class="text-xs text-blue-600 whitespace-nowrap px-2 py-1 bg-blue-50 rounded">메인</span>
									{/if}
									{#if eventUrls.length > 1}
										<button
											type="button"
											onclick={() => removeUrl(index)}
											class="text-gray-400 hover:text-red-500 p-1"
											title="URL 삭제"
										>
											<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
											</svg>
										</button>
									{/if}
								</div>
							{/each}
							<button
								type="button"
								onclick={addUrl}
								class="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1"
							>
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
								</svg>
								URL 추가
							</button>
						</div>
						<p class="mt-1 text-xs text-gray-500">구글폼, 네이버폼 등 참여 URL (첫 번째 URL로 타입 감지)</p>
					</div>

					<!-- 기간 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-start" class="block text-sm font-medium text-gray-700 mb-1"
								>시작일</label
							>
							<input
								id="event-start"
								type="date"
								bind:value={eventForm.event_start}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="event-end" class="block text-sm font-medium text-gray-700 mb-1"
								>종료일</label
							>
							<input
								id="event-end"
								type="date"
								bind:value={eventForm.event_end}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- 주최 + 발표일 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-organizer" class="block text-sm font-medium text-gray-700 mb-1"
								>주최</label
							>
							<input
								id="event-organizer"
								type="text"
								bind:value={eventForm.organizer}
								placeholder="주최자/브랜드명"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="event-announcement" class="block text-sm font-medium text-gray-700 mb-1"
								>발표일</label
							>
							<input
								id="event-announcement"
								type="date"
								bind:value={eventForm.announcement_date}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- 팝업 전용: 위치 -->
					{#if eventForm.event_type === 'popup'}
						<div class="grid grid-cols-2 gap-4">
							<div>
								<label for="event-venue" class="block text-sm font-medium text-gray-700 mb-1"
									>장소명</label
								>
								<input
									id="event-venue"
									type="text"
									bind:value={eventForm.location_venue}
									placeholder="예: 더현대 서울"
									class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
								/>
							</div>
							<div>
								<label for="event-address" class="block text-sm font-medium text-gray-700 mb-1"
									>주소</label
								>
								<input
									id="event-address"
									type="text"
									bind:value={eventForm.location_address}
									placeholder="예: 서울시 영등포구..."
									class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
								/>
							</div>
						</div>
					{/if}

					<!-- 경품 -->
					<div>
						<label for="event-prizes" class="block text-sm font-medium text-gray-700 mb-1"
							>경품</label
						>
						<textarea
							id="event-prizes"
							bind:value={prizesText}
							placeholder="경품을 한 줄에 하나씩 입력&#10;예: 아이패드 프로&#10;에어팟 프로"
							rows="3"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
						></textarea>
						<p class="mt-1 text-xs text-gray-500">한 줄에 하나의 경품 입력</p>
					</div>

					<!-- 당첨자 수 + 조건 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-winner-count" class="block text-sm font-medium text-gray-700 mb-1"
								>당첨자 수</label
							>
							<input
								id="event-winner-count"
								type="number"
								min="0"
								bind:value={eventForm.winner_count}
								placeholder="예: 10"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="event-purchase" class="block text-sm font-medium text-gray-700 mb-1"
								>구매 조건</label
							>
							<select
								id="event-purchase"
								bind:value={eventForm.purchase_required}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							>
								<option value={undefined}>선택 안함</option>
								<option value="no">무료 (구매 불필요)</option>
								<option value="yes_partial">부분 구매 필요</option>
								<option value="yes_all">구매 필수</option>
							</select>
						</div>
					</div>

					<!-- 요약 -->
					<div>
						<label for="event-summary" class="block text-sm font-medium text-gray-700 mb-1"
							>요약</label
						>
						<textarea
							id="event-summary"
							bind:value={eventForm.summary}
							placeholder="이벤트 설명..."
							rows="3"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						></textarea>
					</div>

					<!-- 원본 본문 (접이식) -->
					{#if eventForm.body_text}
						<details class="border border-gray-200 rounded-lg">
							<summary class="px-3 py-2 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-50">
								원본 본문 (펼쳐서 보기)
							</summary>
							<div class="p-3 pt-0">
								<textarea
									id="event-body-text"
									bind:value={eventForm.body_text}
									placeholder="Instagram 캡션, 웹페이지 본문 등..."
									rows="6"
									class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono text-xs"
								></textarea>
								<p class="mt-1 text-xs text-gray-500">검색에 포함되는 원본 텍스트 (Instagram 캡션, 웹페이지 본문 등)</p>
							</div>
						</details>
					{/if}

					<!-- 메모 -->
					<div>
						<label for="event-note" class="block text-sm font-medium text-gray-700 mb-1">메모</label
						>
						<textarea
							id="event-note"
							bind:value={eventForm.user_note}
							placeholder="개인 메모..."
							rows="2"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						></textarea>
					</div>
				</div>

				<div class="mt-6 flex gap-2 justify-end">
					<button onclick={onClose} class="btn btn-secondary btn-sm"> 취소 </button>
					<button
						onclick={handleSave}
						disabled={isSaving}
						class="btn btn-primary btn-sm disabled:opacity-50"
					>
						{#if isSaving}
							저장 중...
						{:else}
							{editingEvent ? '수정' : '등록'}
						{/if}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
