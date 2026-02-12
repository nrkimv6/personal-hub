<script lang="ts">
	import { onMount } from 'svelte';

	interface Settings {
		model: string;
		api_key_anthropic: string;
		api_key_google: string;
		daily_limit: number;
		monthly_limit: number;
		scan_folders: string[];
		filename_patterns: any[];
		year_annotations: Record<number, string>;
	}

	let settings: Settings = {
		model: 'claude_cli',
		api_key_anthropic: '',
		api_key_google: '',
		daily_limit: 10,
		monthly_limit: 100,
		scan_folders: [],
		filename_patterns: [],
		year_annotations: {}
	};

	let loading = false;
	let saving = false;

	onMount(() => {
		loadSettings();
	});

	async function loadSettings() {
		loading = true;
		try {
			const response = await fetch('/api/ic/settings');
			if (response.ok) {
				settings = await response.json();
			}
		} catch (err) {
			console.error('Failed to load settings:', err);
		} finally {
			loading = false;
		}
	}

	async function saveSettings() {
		saving = true;
		try {
			await fetch('/api/ic/settings', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(settings)
			});
			alert('설정이 저장되었습니다.');
		} catch (err) {
			alert('설정 저장 실패');
		} finally {
			saving = false;
		}
	}
</script>

<div class="settings-page">
	<h1>설정</h1>

	{#if loading}
		<div class="loading">로딩 중...</div>
	{:else}
		<div class="settings-form">
			<section>
				<h2>AI 분류 모델</h2>
				<label>
					<input type="radio" bind:group={settings.model} value="claude_cli" />
					Claude CLI (기본, 무료)
				</label>
				<label>
					<input type="radio" bind:group={settings.model} value="gemini_cli" />
					Gemini CLI
				</label>
				<label>
					<input type="radio" bind:group={settings.model} value="api" />
					API 모드 (고속, 유료)
				</label>

				{#if settings.model === 'api'}
					<div class="api-keys">
						<label>
							Anthropic API Key:
							<input type="password" bind:value={settings.api_key_anthropic} placeholder="sk-ant-..." />
						</label>
						<label>
							Google API Key:
							<input type="password" bind:value={settings.api_key_google} placeholder="..." />
						</label>
					</div>
				{/if}
			</section>

			<section>
				<h2>API 리밋</h2>
				<label>
					일일 리밋 (USD):
					<input type="number" bind:value={settings.daily_limit} min="0" step="1" />
				</label>
				<label>
					월간 리밋 (USD):
					<input type="number" bind:value={settings.monthly_limit} min="0" step="10" />
				</label>
			</section>

			<section>
				<h2>스캔 대상 폴더</h2>
				<p>이미지를 스캔할 폴더들을 지정합니다.</p>
				<textarea bind:value={settings.scan_folders} rows="5" placeholder="D:\Photos&#10;D:\Downloads"></textarea>
			</section>

			<section>
				<h2>연도별 메모</h2>
				<p>각 연도의 주요 이벤트를 입력하면 AI 분류 정확도가 향상됩니다.</p>
				<div class="year-annotations">
					{#each Object.entries(settings.year_annotations) as [year, memo]}
						<label>
							{year}:
							<input type="text" bind:value={settings.year_annotations[Number(year)]} placeholder="예: 제주 여행, 이사" />
						</label>
					{/each}
				</div>
			</section>

			<div class="actions">
				<button on:click={saveSettings} disabled={saving}>
					{saving ? '저장 중...' : '설정 저장'}
				</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.settings-page { padding: 2rem; max-width: 900px; margin: 0 auto; }
	h1 { font-size: 1.8rem; margin-bottom: 2rem; }
	h2 { font-size: 1.3rem; margin-bottom: 1rem; }
	.loading { text-align: center; padding: 3rem; color: #666; }
	.settings-form { display: flex; flex-direction: column; gap: 2rem; }
	section { padding: 1.5rem; border: 1px solid #ddd; border-radius: 8px; background: white; }
	label { display: block; margin-bottom: 1rem; }
	input[type="radio"] { margin-right: 0.5rem; }
	input[type="text"], input[type="password"], input[type="number"], textarea {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		margin-top: 0.25rem;
	}
	.api-keys { margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #eee; }
	.year-annotations { display: flex; flex-direction: column; gap: 0.5rem; }
	.actions { text-align: center; }
	button { padding: 0.75rem 2rem; background: #007bff; color: white; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; }
	button:disabled { background: #ccc; }
	button:hover:not(:disabled) { background: #0056b3; }
</style>
