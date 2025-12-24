<script lang="ts">
	/**
	 * 이벤트 생성/수정 모달 컴포넌트
	 */
	import type { Event, EventCreate, EventUpdate } from '$lib/types';
	import { prizesToText, textToPrizes } from '$lib/utils/eventUtils';

	interface Props {
		show: boolean;
		editingEvent: Event | null;
		activeTab?: 'event' | 'popup';
		onClose: () => void;
		onSave: (data: EventCreate | EventUpdate, isEdit: boolean) => Promise<void>;
	}

	let { show, editingEvent, activeTab = 'event', onClose, onSave }: Props = $props();

	// 폼 상태
	let eventForm: EventCreate = $state({
		title: '',
		event_type: 'event'
	});
	let prizesText = $state('');
	let isSaving = $state(false);

	// editingEvent가 변경되면 폼 초기화
	$effect(() => {
		if (show) {
			if (editingEvent) {
				eventForm = {
					title: editingEvent.title,
					event_type: editingEvent.event_type,
					event_url: editingEvent.event_url || '',
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
					user_note: editingEvent.user_note || ''
				};
				prizesText = prizesToText(editingEvent.prizes);
			} else {
				eventForm = {
					title: '',
					event_type: activeTab === 'popup' ? 'popup' : 'event',
					event_url: '',
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
			const formData = {
				...eventForm,
				prizes: textToPrizes(prizesText)
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
							{editingEvent ? '이벤트 수정' : '새 이벤트'}
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

					<!-- 이벤트 URL -->
					<div>
						<label for="event-url" class="block text-sm font-medium text-gray-700 mb-1"
							>이벤트 URL</label
						>
						<input
							id="event-url"
							type="text"
							bind:value={eventForm.event_url}
							placeholder="https://..."
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>
						<p class="mt-1 text-xs text-gray-500">구글폼, 네이버폼 등 참여 URL (자동으로 타입 감지)</p>
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
