<script lang="ts">
	import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';
	import TabNav from '$lib/components/layout/TabNav.svelte';

	// Types
	interface SleepStatus {
		is_active: boolean;
		mode: string;
		block_start: string | null;
		block_end: string | null;
		grace_until: string | null;
		bypass_attempts_today: number;
	}

	interface Schedule {
		warning_times: string[];
		block_start: string;
		block_end: string;
	}

	interface LogEntry {
		timestamp: string;
		type: string;
		reason?: string;
		details?: Record<string, unknown>;
	}

	interface DailyStats {
		date: string;
		bypass_attempts: number;
		emergency_unlocks: number;
		estimated_sleep_time?: string;
	}

	// State
	let status = $state<SleepStatus | null>(null);
	let schedule = $state<Schedule | null>(null);
	let logs = $state<LogEntry[]>([]);
	let stats = $state<DailyStats[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Emergency unlock form
	let password = $state('');
	let reason = $state('');
	let unlocking = $state(false);
	let unlockError = $state<string | null>(null);
	let unlockSuccess = $state<string | null>(null);

	// Tab state
	let activeTab = $state<'status' | 'settings'>('status');

	const sleepTabs = [
		{ id: 'status', label: '상태 모니터링' },
		{ id: 'settings', label: '설정' },
	];

	$effect(() => {
		if (activeTab === 'settings') initializeSettingsForm();
	});

	// Settings form state
	let settingsPassword = $state('');
	let warningTimesInput = $state('');
	let blockStartInput = $state('');
	let blockEndInput = $state('');
	let settingsSaving = $state(false);
	let settingsError = $state<string | null>(null);
	let settingsSuccess = $state<string | null>(null);

	// Password change form state
	let currentPassword = $state('');
	let newPassword = $state('');
	let confirmPassword = $state('');
	let passwordChanging = $state(false);
	let passwordError = $state<string | null>(null);
	let passwordSuccess = $state<string | null>(null);

	const API_BASE = '/api/v1/sleep-now';

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const [statusRes, scheduleRes, logsRes, statsRes] = await Promise.all([
				fetch(`${API_BASE}/status`),
				fetch(`${API_BASE}/schedule`),
				fetch(`${API_BASE}/logs?days=7`),
				fetch(`${API_BASE}/stats?days=7`)
			]);

			if (!statusRes.ok) throw new Error('상태 조회 실패');

			status = await statusRes.json();
			schedule = await scheduleRes.json();
			logs = await logsRes.json();
			stats = await statsRes.json();
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function emergencyUnlock() {
		if (!password) {
			unlockError = '비밀번호를 입력하세요';
			return;
		}

		unlocking = true;
		unlockError = null;
		unlockSuccess = null;

		try {
			const res = await fetchWithTimeout(`${API_BASE}/emergency-unlock`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ password, reason })
			});

			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.detail || '잠금 해제 실패');
			}

			const data = await res.json();
			unlockSuccess = data.message;
			password = '';
			reason = '';
			await fetchData();
		} catch (e) {
			unlockError = e instanceof Error ? e.message : '잠금 해제 실패';
		} finally {
			unlocking = false;
		}
	}

	async function skipToday() {
		if (!password) {
			unlockError = '비밀번호를 입력하세요';
			return;
		}

		unlocking = true;
		unlockError = null;
		unlockSuccess = null;

		try {
			const res = await fetchWithTimeout(`${API_BASE}/skip-today`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ password, reason })
			});

			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.detail || '하루 비활성화 실패');
			}

			const data = await res.json();
			unlockSuccess = data.message;
			password = '';
			reason = '';
			await fetchData();
		} catch (e) {
			unlockError = e instanceof Error ? e.message : '하루 비활성화 실패';
		} finally {
			unlocking = false;
		}
	}

	async function updateSchedule() {
		if (!settingsPassword) {
			settingsError = '비밀번호를 입력하세요';
			return;
		}

		settingsSaving = true;
		settingsError = null;
		settingsSuccess = null;

		try {
			const body: Record<string, unknown> = { password: settingsPassword };

			// Parse warning times
			if (warningTimesInput.trim()) {
				const times = warningTimesInput
					.split(',')
					.map((t) => t.trim())
					.filter((t) => t);
				if (times.length > 0) body.warning_times = times;
			}

			// Add block times if provided
			if (blockStartInput.trim()) body.block_start = blockStartInput.trim();
			if (blockEndInput.trim()) body.block_end = blockEndInput.trim();

			const res = await fetchWithTimeout(`${API_BASE}/schedule`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});

			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.detail || '스케줄 업데이트 실패');
			}

			const data = await res.json();
			settingsSuccess = data.message;
			settingsPassword = '';
			await fetchData();
		} catch (e) {
			settingsError = e instanceof Error ? e.message : '스케줄 업데이트 실패';
		} finally {
			settingsSaving = false;
		}
	}

	async function changePassword() {
		if (!currentPassword) {
			passwordError = '현재 비밀번호를 입력하세요';
			return;
		}

		if (!newPassword || newPassword.length < 4) {
			passwordError = '새 비밀번호는 4자 이상이어야 합니다';
			return;
		}

		if (newPassword !== confirmPassword) {
			passwordError = '새 비밀번호가 일치하지 않습니다';
			return;
		}

		passwordChanging = true;
		passwordError = null;
		passwordSuccess = null;

		try {
			const res = await fetchWithTimeout(`${API_BASE}/password`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					current_password: currentPassword,
					new_password: newPassword,
					confirm_password: confirmPassword
				})
			});

			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.detail || '비밀번호 변경 실패');
			}

			const data = await res.json();
			passwordSuccess = data.message;
			currentPassword = '';
			newPassword = '';
			confirmPassword = '';
		} catch (e) {
			passwordError = e instanceof Error ? e.message : '비밀번호 변경 실패';
		} finally {
			passwordChanging = false;
		}
	}

	function initializeSettingsForm() {
		if (schedule) {
			warningTimesInput = schedule.warning_times.join(', ');
			blockStartInput = schedule.block_start;
			blockEndInput = schedule.block_end;
		}
	}

	function formatDateTime(iso: string | null): string {
		if (!iso) return '-';
		return new Date(iso).toLocaleString('ko-KR');
	}

	function getStatusColor(mode: string): string {
		switch (mode) {
			case 'blocking':
				return 'bg-error-light text-error border-red-200';
			case 'warning':
				return 'bg-warning-light text-warning-foreground border-yellow-200';
			case 'grace':
				return 'bg-primary-light text-primary border-blue-200';
			default:
				return 'bg-muted text-foreground border-border';
		}
	}

	function getStatusText(mode: string): string {
		switch (mode) {
			case 'blocking':
				return '차단 중';
			case 'warning':
				return '경고 중';
			case 'grace':
				return '유예 중';
			case 'disabled':
				return '비활성';
			default:
				return mode;
		}
	}

	function getLogTypeColor(type: string): string {
		switch (type) {
			case 'block_start':
				return 'bg-error-light text-error';
			case 'block_end':
				return 'bg-success-light text-success';
			case 'bypass_attempt':
				return 'bg-warning-light text-warning';
			case 'emergency_unlock':
				return 'bg-primary-light text-primary';
			case 'skip_today':
				return 'bg-purple-light text-purple';
			default:
				return 'bg-muted text-foreground';
		}
	}

	function getLogTypeText(type: string): string {
		switch (type) {
			case 'block_start':
				return '차단 시작';
			case 'block_end':
				return '차단 해제';
			case 'bypass_attempt':
				return '우회 시도';
			case 'emergency_unlock':
				return '긴급 해제';
			case 'emergency_unlock_failed':
				return '해제 실패';
			case 'skip_today':
				return '오늘 비활성화';
			default:
				return type;
		}
	}

	onMount(() => {
		fetchData();
		// Auto refresh every 30 seconds
		const interval = setInterval(fetchData, 30000);
		return () => clearInterval(interval);
	});
</script>

<div>
	<div class="mb-6 flex items-center justify-between">
		<h2 class="text-xl font-semibold text-foreground">Sleep Now</h2>
		<button
			onclick={fetchData}
			class="px-4 py-2 text-sm bg-muted hover:bg-secondary rounded-lg transition-colors"
		>
			새로고침
		</button>
	</div>

	<!-- Tab Navigation -->
	<TabNav tabs={sleepTabs} bind:activeTab variant="secondary" />

	{#if loading && !status}
		<div class="flex items-center justify-center h-64">
			<div class="text-muted-foreground">로딩 중...</div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 rounded-lg p-4 text-error">
			{error}
		</div>
	{:else if activeTab === 'status'}
		<!-- Status Tab -->
		<!-- Status Card -->
		<div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
			<!-- Current Status -->
			<div class="bg-card border border-border rounded-lg shadow-sm p-6">
				<h2 class="text-lg font-semibold text-foreground mb-4">현재 상태</h2>
				{#if status}
					<div class="space-y-3">
						<div class="flex items-center gap-3">
							<span
								class="px-3 py-1 rounded-full text-sm font-medium border {getStatusColor(
									status.mode
								)}"
							>
								{getStatusText(status.mode)}
							</span>
							<div class="flex items-center justify-center h-10 w-10 rounded-full bg-indigo-50 dark:bg-indigo-900/30">
								{#if status.is_active}
									<svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
								{:else}
									<svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>
								{/if}
							</div>
						</div>

						{#if status.block_start}
							<div class="text-sm text-muted-foreground">
								<span class="font-medium">차단 시작:</span>
								{formatDateTime(status.block_start)}
							</div>
						{/if}
						{#if status.block_end}
							<div class="text-sm text-muted-foreground">
								<span class="font-medium">차단 해제:</span>
								{formatDateTime(status.block_end)}
							</div>
						{/if}
						{#if status.grace_until}
							<div class="text-sm text-primary">
								<span class="font-medium">유예 종료:</span>
								{formatDateTime(status.grace_until)}
							</div>
						{/if}
						<div class="text-sm text-muted-foreground">
							<span class="font-medium">오늘 우회 시도:</span>
							<span class="text-warning font-semibold">{status.bypass_attempts_today}회</span>
						</div>
					</div>
				{/if}
			</div>

			<!-- Schedule -->
			<div class="bg-card border border-border rounded-lg shadow-sm p-6">
				<h2 class="text-lg font-semibold text-foreground mb-4">스케줄</h2>
				{#if schedule}
					<div class="space-y-3">
						<div class="text-sm">
							<span class="font-medium text-foreground">차단 시작:</span>
							<span class="text-error font-semibold">{schedule.block_start}</span>
						</div>
						<div class="text-sm">
							<span class="font-medium text-foreground">차단 해제:</span>
							<span class="text-success font-semibold">{schedule.block_end}</span>
						</div>
						<div class="text-sm">
							<span class="font-medium text-foreground">경고 시간:</span>
							<div class="mt-1 flex flex-wrap gap-1">
								{#each schedule.warning_times as time}
									<span class="px-2 py-0.5 bg-warning-light text-warning-foreground text-xs rounded">
										{time}
									</span>
								{/each}
							</div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Weekly Stats -->
			<div class="bg-card border border-border rounded-lg shadow-sm p-6">
				<h2 class="text-lg font-semibold text-foreground mb-4">주간 통계</h2>
				{#if stats.length > 0}
					<div class="space-y-2">
						<div class="text-sm">
							<span class="font-medium text-foreground">총 우회 시도:</span>
							<span class="text-warning font-semibold">
								{stats.reduce((sum, s) => sum + s.bypass_attempts, 0)}회
							</span>
						</div>
						<div class="text-sm">
							<span class="font-medium text-foreground">긴급 해제:</span>
							<span class="text-primary font-semibold">
								{stats.reduce((sum, s) => sum + s.emergency_unlocks, 0)}회
							</span>
						</div>
					</div>
				{:else}
					<div class="text-sm text-muted-foreground">통계 없음</div>
				{/if}
			</div>
		</div>

		<!-- Emergency Unlock -->
		<div class="bg-card border border-border rounded-lg shadow-sm p-6 mb-6">
			<h2 class="text-lg font-semibold text-foreground mb-4">긴급 해제</h2>
			<p class="text-sm text-muted-foreground mb-4">
				긴급한 경우 아래 비밀번호를 입력하여 1시간 유예를 받을 수 있습니다. 비밀번호는 16자 이상이어야
				합니다.
			</p>

			{#if unlockError}
				<div class="mb-4 p-3 bg-error-light border border-red-200 rounded-lg text-error text-sm">
					{unlockError}
				</div>
			{/if}
			{#if unlockSuccess}
				<div class="mb-4 p-3 bg-success-light border border-green-200 rounded-lg text-success text-sm">
					{unlockSuccess}
				</div>
			{/if}

			<div class="space-y-4">
				<div>
					<label for="password" class="block text-sm font-medium text-foreground mb-1">
						비밀번호
					</label>
					<input
						type="password"
						id="password"
						bind:value={password}
						class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
						placeholder="비밀번호 입력"
					/>
				</div>
				<div>
					<label for="reason" class="block text-sm font-medium text-foreground mb-1">
						사유 (선택)
					</label>
					<input
						type="text"
						id="reason"
						bind:value={reason}
						class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
						placeholder="해제 사유 입력"
					/>
				</div>
				<div class="flex gap-3">
					<button
						onclick={emergencyUnlock}
						disabled={unlocking}
						class="px-4 py-2 bg-primary hover:bg-primary-hover disabled:bg-blue-400 text-white rounded-lg transition-colors"
					>
						{unlocking ? '처리 중...' : '1시간 유예'}
					</button>
					<button
						onclick={skipToday}
						disabled={unlocking}
						class="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-400 text-white rounded-lg transition-colors"
					>
						{unlocking ? '처리 중...' : '오늘 하루 비활성화'}
					</button>
				</div>
			</div>
		</div>

		<!-- Recent Logs -->
		<div class="bg-card border border-border rounded-lg shadow-sm p-6">
			<h2 class="text-lg font-semibold text-foreground mb-4">최근 로그</h2>
			{#if logs.length > 0}
				<div class="overflow-x-auto">
					<table class="w-full text-sm">
						<thead class="bg-background">
							<tr>
								<th class="px-4 py-2 text-left font-medium text-muted-foreground">시간</th>
								<th class="px-4 py-2 text-left font-medium text-muted-foreground">유형</th>
								<th class="px-4 py-2 text-left font-medium text-muted-foreground">상세</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each logs.slice(0, 20) as log}
								<tr class="hover:bg-muted">
									<td class="px-4 py-2 text-muted-foreground">
										{new Date(log.timestamp).toLocaleString('ko-KR')}
									</td>
									<td class="px-4 py-2">
										<span
											class="px-2 py-0.5 rounded text-xs font-medium {getLogTypeColor(log.type)}"
										>
											{getLogTypeText(log.type)}
										</span>
									</td>
									<td class="px-4 py-2 text-muted-foreground">
										{#if log.reason}
											{log.reason}
										{:else if log.details}
											{JSON.stringify(log.details)}
										{:else}
											-
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<div class="text-sm text-muted-foreground text-center py-8">로그 없음</div>
			{/if}
		</div>
	{:else if activeTab === 'settings'}
		<!-- Settings Tab -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<!-- Schedule Settings -->
			<div class="bg-card border border-border rounded-lg shadow-sm p-6">
				<h2 class="text-lg font-semibold text-foreground mb-4">스케줄 설정</h2>
				<p class="text-sm text-muted-foreground mb-4">
					경고 시간과 차단 시간을 변경할 수 있습니다. 변경 후에는 서비스 재시작이 필요합니다.
				</p>

				{#if settingsError}
					<div class="mb-4 p-3 bg-error-light border border-red-200 rounded-lg text-error text-sm">
						{settingsError}
					</div>
				{/if}
				{#if settingsSuccess}
					<div class="mb-4 p-3 bg-success-light border border-green-200 rounded-lg text-success text-sm">
						{settingsSuccess}
					</div>
				{/if}

				<div class="space-y-4">
					<div>
						<label for="warningTimes" class="block text-sm font-medium text-foreground mb-1">
							경고 시간 (쉼표로 구분)
						</label>
						<input
							type="text"
							id="warningTimes"
							bind:value={warningTimesInput}
							class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							placeholder="예: 23:00, 23:30, 23:45, 23:50"
						/>
						<p class="mt-1 text-xs text-muted-foreground">HH:MM 형식으로 입력하세요</p>
					</div>

					<div class="grid grid-cols-2 gap-3">
						<div>
							<label for="blockStart" class="block text-sm font-medium text-foreground mb-1">
								차단 시작
							</label>
							<input
								type="text"
								id="blockStart"
								bind:value={blockStartInput}
								class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
								placeholder="00:00"
							/>
						</div>
						<div>
							<label for="blockEnd" class="block text-sm font-medium text-foreground mb-1">
								차단 해제
							</label>
							<input
								type="text"
								id="blockEnd"
								bind:value={blockEndInput}
								class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
								placeholder="07:00"
							/>
						</div>
					</div>

					<div>
						<label for="settingsPassword" class="block text-sm font-medium text-foreground mb-1">
							비밀번호 (16자 이상)
						</label>
						<input
							type="password"
							id="settingsPassword"
							bind:value={settingsPassword}
							class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							placeholder="비밀번호 입력"
						/>
					</div>

					<button
						onclick={updateSchedule}
						disabled={settingsSaving}
						class="w-full px-4 py-2 bg-primary hover:bg-primary-hover disabled:bg-blue-400 text-white rounded-lg transition-colors"
					>
						{settingsSaving ? '저장 중...' : '설정 저장'}
					</button>

					{#if settingsSuccess}
						<div class="p-3 bg-warning-light border border-yellow-200 rounded-lg text-warning-foreground text-sm">
							설정이 변경되었습니다. 서비스 재시작이 필요합니다.
						</div>
					{/if}
				</div>
			</div>

			<!-- Password Change -->
			<div class="bg-card border border-border rounded-lg shadow-sm p-6">
				<h2 class="text-lg font-semibold text-foreground mb-4">비밀번호 변경</h2>
				<p class="text-sm text-muted-foreground mb-4">
					긴급 해제 및 설정 변경에 사용되는 비밀번호를 변경합니다.
				</p>

				{#if passwordError}
					<div class="mb-4 p-3 bg-error-light border border-red-200 rounded-lg text-error text-sm">
						{passwordError}
					</div>
				{/if}
				{#if passwordSuccess}
					<div class="mb-4 p-3 bg-success-light border border-green-200 rounded-lg text-success text-sm">
						{passwordSuccess}
					</div>
				{/if}

				<div class="space-y-4">
					<div>
						<label for="currentPassword" class="block text-sm font-medium text-foreground mb-1">
							현재 비밀번호
						</label>
						<input
							type="password"
							id="currentPassword"
							bind:value={currentPassword}
							class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							placeholder="현재 비밀번호"
						/>
					</div>

					<div>
						<label for="newPassword" class="block text-sm font-medium text-foreground mb-1">
							새 비밀번호 (16자 이상)
						</label>
						<input
							type="password"
							id="newPassword"
							bind:value={newPassword}
							class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							placeholder="새 비밀번호"
						/>
					</div>

					<div>
						<label for="confirmPassword" class="block text-sm font-medium text-foreground mb-1">
							새 비밀번호 확인
						</label>
						<input
							type="password"
							id="confirmPassword"
							bind:value={confirmPassword}
							class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
							placeholder="새 비밀번호 확인"
						/>
					</div>

					<button
						onclick={changePassword}
						disabled={passwordChanging}
						class="w-full px-4 py-2 bg-primary hover:bg-primary-hover disabled:bg-blue-400 text-white rounded-lg transition-colors"
					>
						{passwordChanging ? '변경 중...' : '비밀번호 변경'}
					</button>
				</div>
			</div>
		</div>
	{/if}
</div>
