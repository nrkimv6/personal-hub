<script lang="ts">
	import { onMount } from 'svelte';
	import { notificationApi } from '$lib/api';
	import type { NotificationSettings } from '$lib/types';
	import Button from '$lib/components/ui/Button.svelte';
	import { toast } from '$lib/stores/toast';

	let notificationSettings: NotificationSettings | null = null;
	let loading = true;
	let saving = false;
	let error: string | null = null;

	function errorMessage(e: unknown): string {
		return e instanceof Error ? e.message : '알 수 없는 오류';
	}

	const notifyStateOptions = [
		{ value: 'available', label: '예약 가능 발견' },
		{ value: 'booking_success', label: '예약 성공' },
		{ value: 'booking_failed', label: '예약 실패' },
		{ value: 'error', label: '오류 발생' },
		{ value: 'popup_new', label: '팝업 신규 감지' }
	];

	const allowedNotifyStates = new Set(notifyStateOptions.map((option) => option.value));

	export async function fetchData() {
		loading = true;
		try {
			const settings = await notificationApi.getSettings();
			notificationSettings = {
				...settings,
				notify_states: settings.notify_states.filter((state) => allowedNotifyStates.has(state))
			};
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function saveNotificationSettings() {
		if (!notificationSettings) return;
		saving = true;
		try {
			await notificationApi.updateSettings(notificationSettings);
			toast.success('설정이 저장되었습니다.');
		} catch (e) {
			toast.error('저장 실패: ' + errorMessage(e));
		} finally {
			saving = false;
		}
	}

	function toggleNotifyState(state: string) {
		if (!notificationSettings) return;
		const index = notificationSettings.notify_states.indexOf(state);
		if (index >= 0) {
			notificationSettings.notify_states = notificationSettings.notify_states.filter(
				(s) => s !== state
			);
		} else {
			notificationSettings.notify_states = [...notificationSettings.notify_states, state];
		}
	}

	onMount(fetchData);
</script>

<div>
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else}
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<!-- 알림 설정 -->
			<div class="card">
				<h3 class="text-lg font-semibold text-foreground mb-4">알림 설정</h3>

				{#if notificationSettings}
					<div class="space-y-4">
						<div class="flex items-center justify-between">
							<div>
								<p class="font-medium">텔레그램 알림</p>
								<p class="text-sm text-muted-foreground">텔레그램으로 알림을 받습니다.</p>
							</div>
							<label class="relative inline-flex items-center cursor-pointer">
								<input
									type="checkbox"
									class="sr-only peer"
									bind:checked={notificationSettings.enable_telegram}
								/>
								<div
									class="w-11 h-6 bg-secondary peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"
								></div>
							</label>
						</div>

						<div class="flex items-center justify-between">
							<div>
								<p class="font-medium">데스크톱 알림</p>
								<p class="text-sm text-muted-foreground">시스템 알림을 표시합니다.</p>
							</div>
							<label class="relative inline-flex items-center cursor-pointer">
								<input
									type="checkbox"
									class="sr-only peer"
									bind:checked={notificationSettings.enable_desktop}
								/>
								<div
									class="w-11 h-6 bg-secondary peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"
								></div>
							</label>
						</div>

						<hr />

						<div>
							<p class="font-medium mb-2">알림 받을 상태</p>
							<div class="space-y-2">
								{#each notifyStateOptions as option}
									<label class="flex items-center gap-2 cursor-pointer">
										<input
											type="checkbox"
											checked={notificationSettings.notify_states.includes(option.value)}
											onchange={() => toggleNotifyState(option.value)}
											class="rounded border-border text-primary focus:ring-ring"
										/>
										<span class="text-sm">{option.label}</span>
									</label>
								{/each}
							</div>
						</div>

						<Button
							variant="primary" class="w-full"
							onclick={saveNotificationSettings}
							disabled={saving}
						>
							{saving ? '저장 중...' : '설정 저장'}
						</Button>
					</div>
				{/if}
			</div>

			<!-- API 문서 링크 -->
			<div class="card">
				<h3 class="text-lg font-semibold text-foreground mb-4">API 문서</h3>
				<div class="flex gap-4">
					<a href="/docs" target="_blank" class="inline-flex items-center px-4 py-2 rounded bg-secondary text-secondary-foreground hover:bg-secondary/80"> Swagger UI </a>
					<a href="/redoc" target="_blank" class="inline-flex items-center px-4 py-2 rounded bg-secondary text-secondary-foreground hover:bg-secondary/80"> ReDoc </a>
				</div>
			</div>
		</div>
	{/if}
</div>
