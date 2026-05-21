<script lang="ts">
	import { onMount } from 'svelte';
	import { notificationApi } from '$lib/api';
	import type {
		AlertRuleChannel,
		AlertRuleOverrideUpdate,
		AlertRuleSettings,
		AlertRuleSeverity,
		NotificationSettings
	} from '$lib/types';
	import Button from '$lib/components/ui/Button.svelte';
	import { toast } from '$lib/stores/toast';

	let notificationSettings: NotificationSettings | null = null;
	let alertRules: AlertRuleSettings[] = [];
	let loading = true;
	let saving = false;
	let savingRuleId: string | null = null;
	let error: string | null = null;
	let ruleError: string | null = null;

	function errorMessage(e: unknown): string {
		return e instanceof Error ? e.message : '알 수 없는 오류';
	}

	const notifyStateOptions = [
		{ value: 'available', label: '예약 가능 발견' },
		{ value: 'booking_success', label: '예약 성공' },
		{ value: 'booking_failed', label: '예약 실패' },
		{ value: 'error', label: '오류 발생' },
		{ value: 'popup_new', label: '팝업 신규 감지' },
		{ value: 'failure_warning', label: '운영 실패 경고' }
	];

	const allowedNotifyStates = new Set(notifyStateOptions.map((option) => option.value));
	const severityOptions: Array<{ value: AlertRuleSeverity; label: string }> = [
		{ value: 'critical', label: 'Critical' },
		{ value: 'warning', label: 'Warning' },
		{ value: 'record_only', label: 'Record only' }
	];
	const channelOptions: Array<{ value: AlertRuleChannel; label: string }> = [
		{ value: 'telegram', label: 'Telegram' },
		{ value: 'desktop', label: 'Desktop' },
		{ value: 'ui_only', label: 'UI only' }
	];

	export async function fetchData() {
		loading = true;
		try {
			const settings = await notificationApi.getSettings();
			const rules = await notificationApi.getAlertRules();
			notificationSettings = {
				...settings,
				notify_states: settings.notify_states.filter((state) => allowedNotifyStates.has(state))
			};
			alertRules = rules;
			error = null;
			ruleError = null;
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

	function updateRule(ruleId: string, patch: Partial<AlertRuleSettings>) {
		alertRules = alertRules.map((rule) => (rule.rule_id === ruleId ? { ...rule, ...patch } : rule));
	}

	function normalizeRuleError(e: unknown): string {
		const message = errorMessage(e);
		if (message.includes('ALERT_RULE_STALE_WRITE')) return 'ALERT_RULE_STALE_WRITE: rule has changed. Reload and try again.';
		if (message.includes('LOCKED_CRITICAL_RULE')) return 'LOCKED_CRITICAL_RULE: critical locked rules cannot be disabled or downgraded.';
		if (message.includes('ALERT_POLICY_REGISTRY_MISSING')) return 'ALERT_POLICY_REGISTRY_MISSING: failure alert registry is unavailable.';
		return message;
	}

	async function saveAlertRule(rule: AlertRuleSettings) {
		if (rule.stale) return;
		savingRuleId = rule.rule_id;
		ruleError = null;
		const payload: AlertRuleOverrideUpdate = {
			enabled: rule.enabled,
			severity_override: rule.severity_override,
			channel_override: rule.channel_override,
			cooldown_seconds: rule.cooldown_seconds,
			burst_threshold: rule.burst_threshold,
			expected_version: rule.version
		};
		try {
			const response = await notificationApi.updateAlertRule(rule.rule_id, payload);
			updateRule(rule.rule_id, response.rule);
			toast.success('Rule setting saved.');
		} catch (e) {
			ruleError = normalizeRuleError(e);
			toast.error('Rule save failed: ' + ruleError);
		} finally {
			savingRuleId = null;
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

			<div class="lg:col-span-2">
				<div class="card">
					<div class="flex items-center justify-between mb-4">
						<h3 class="text-lg font-semibold text-foreground">Alert rule settings</h3>
						<Button variant="secondary" onclick={fetchData} disabled={loading || savingRuleId !== null}>
							Reload
						</Button>
					</div>

					{#if ruleError}
						<div class="mb-3 border border-red-200 bg-error-light text-error px-3 py-2 rounded">
							{ruleError}
						</div>
					{/if}

					<div class="overflow-x-auto">
						<table class="min-w-full text-sm">
							<thead>
								<tr class="border-b border-border text-left text-muted-foreground">
									<th class="py-2 pr-3 font-medium">Source</th>
									<th class="py-2 pr-3 font-medium">Enabled</th>
									<th class="py-2 pr-3 font-medium">Severity</th>
									<th class="py-2 pr-3 font-medium">Channel</th>
									<th class="py-2 pr-3 font-medium">Cooldown</th>
									<th class="py-2 pr-3 font-medium">Burst</th>
									<th class="py-2 pr-3 font-medium">State</th>
									<th class="py-2 font-medium">Action</th>
								</tr>
							</thead>
							<tbody>
								{#each alertRules as rule (rule.rule_id)}
									<tr class="border-b border-border align-top">
										<td class="py-3 pr-3">
											<div class="font-medium text-foreground">{rule.source}</div>
											<div class="text-xs text-muted-foreground">{rule.rule_id}</div>
										</td>
										<td class="py-3 pr-3">
											<input
												type="checkbox"
												checked={rule.enabled}
												disabled={rule.locked || rule.stale}
												onchange={(event) =>
													updateRule(rule.rule_id, {
														enabled: (event.currentTarget as HTMLInputElement).checked
													})}
												class="rounded border-border text-primary focus:ring-ring"
											/>
										</td>
										<td class="py-3 pr-3">
											<select
												value={rule.severity_override ?? rule.effective_severity}
												disabled={rule.locked || rule.stale}
												onchange={(event) =>
													updateRule(rule.rule_id, {
														severity_override: (event.currentTarget as HTMLSelectElement).value as AlertRuleSeverity
													})}
												class="border border-border rounded px-2 py-1 bg-background"
											>
												{#each severityOptions as option}
													<option value={option.value}>{option.label}</option>
												{/each}
											</select>
											<div class="text-xs text-muted-foreground mt-1">
												default {rule.default_severity}
											</div>
										</td>
										<td class="py-3 pr-3">
											<select
												value={rule.channel_override ?? rule.effective_channel}
												disabled={rule.stale}
												onchange={(event) =>
													updateRule(rule.rule_id, {
														channel_override: (event.currentTarget as HTMLSelectElement).value as AlertRuleChannel
													})}
												class="border border-border rounded px-2 py-1 bg-background"
											>
												{#each channelOptions as option}
													<option value={option.value}>{option.label}</option>
												{/each}
											</select>
										</td>
										<td class="py-3 pr-3">
											<input
												type="number"
												min="0"
												value={rule.cooldown_seconds}
												disabled={rule.stale}
												oninput={(event) =>
													updateRule(rule.rule_id, {
														cooldown_seconds: Number((event.currentTarget as HTMLInputElement).value || 0)
													})}
												class="w-24 border border-border rounded px-2 py-1 bg-background"
											/>
										</td>
										<td class="py-3 pr-3">
											<input
												type="number"
												min="1"
												value={rule.burst_threshold ?? ''}
												disabled={rule.stale}
												oninput={(event) => {
													const value = (event.currentTarget as HTMLInputElement).value;
													updateRule(rule.rule_id, { burst_threshold: value ? Number(value) : null });
												}}
												class="w-20 border border-border rounded px-2 py-1 bg-background"
											/>
										</td>
										<td class="py-3 pr-3">
											<div class="flex flex-wrap gap-1">
												{#if rule.locked}
													<span class="px-2 py-0.5 rounded bg-red-50 text-red-700 border border-red-200">locked critical</span>
												{/if}
												{#if rule.stale}
													<span class="px-2 py-0.5 rounded bg-yellow-50 text-yellow-700 border border-yellow-200">stale override</span>
												{/if}
												{#if rule.has_override}
													<span class="px-2 py-0.5 rounded bg-secondary text-secondary-foreground">override</span>
												{/if}
											</div>
										</td>
										<td class="py-3">
											<Button
												variant="primary"
												onclick={() => saveAlertRule(rule)}
												disabled={rule.stale || savingRuleId === rule.rule_id}
											>
												{savingRuleId === rule.rule_id ? 'Saving...' : 'Save'}
											</Button>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
