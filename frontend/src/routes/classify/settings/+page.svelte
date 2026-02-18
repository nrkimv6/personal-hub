<script lang="ts">
	import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';

	interface Settings {
		scan_root_folders: string[];
		image_extensions: string[];
		max_files_per_scan: number;
		phash_hash_size: number;
		phash_duplicate_threshold: number;
		clip_model_name: string;
		clip_batch_size: number;
		clip_use_gpu: boolean;
		faiss_similarity_threshold: number;
		thumbnail_size: [number, number];
		thumbnail_quality: number;
		ai_mode: string;
		claude_cli_path: string;
		gemini_cli_path: string;
		cli_max_workers: number;
		cli_timeout_seconds: number;
		cluster_gap_minutes: number;
		target_root_folder: string | null;
		use_trash: boolean;
		max_workers_per_task: number;
	}

	let settings: Settings = {
		scan_root_folders: [],
		image_extensions: [],
		max_files_per_scan: 300000,
		phash_hash_size: 16,
		phash_duplicate_threshold: 10,
		clip_model_name: 'clip-ViT-B-32',
		clip_batch_size: 64,
		clip_use_gpu: true,
		faiss_similarity_threshold: 0.85,
		thumbnail_size: [300, 300],
		thumbnail_quality: 85,
		ai_mode: 'cli',
		claude_cli_path: 'claude',
		gemini_cli_path: 'gemini',
		cli_max_workers: 2,
		cli_timeout_seconds: 30,
		cluster_gap_minutes: 60,
		target_root_folder: null,
		use_trash: true,
		max_workers_per_task: 4
	};

	let loading = false;
	let saving = false;

	onMount(() => {
		loadSettings();
	});

	async function loadSettings() {
		loading = true;
		try {
			const response = await fetchWithTimeout('/api/ic/settings');
			if (response.ok) {
				const data = await response.json();
				settings = { ...settings, ...data };
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
			const response = await fetchWithTimeout('/api/ic/settings', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					scan_root_folders: settings.scan_root_folders,
					max_files_per_scan: settings.max_files_per_scan,
					phash_duplicate_threshold: settings.phash_duplicate_threshold,
					clip_batch_size: settings.clip_batch_size,
					clip_use_gpu: settings.clip_use_gpu,
					faiss_similarity_threshold: settings.faiss_similarity_threshold,
					ai_mode: settings.ai_mode,
					cli_max_workers: settings.cli_max_workers,
					cli_timeout_seconds: settings.cli_timeout_seconds,
					cluster_gap_minutes: settings.cluster_gap_minutes,
					target_root_folder: settings.target_root_folder,
					use_trash: settings.use_trash
				})
			});
			if (response.ok) {
				alert('설정이 저장되었습니다.');
			} else {
				alert('설정 저장 실패');
			}
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
				<h2>AI 분류 모드</h2>
				<label>
					<input type="radio" bind:group={settings.ai_mode} value="cli" />
					CLI 모드 (기본, 무료)
				</label>
				<label>
					<input type="radio" bind:group={settings.ai_mode} value="api" />
					API 모드 (고속, 유료)
				</label>
			</section>

			<section>
				<h2>스캔 설정</h2>
				<label>
					스캔 대상 폴더 (한 줄에 하나씩):
					<textarea bind:value={settings.scan_root_folders} rows="3" placeholder="D:\Photos&#10;D:\Downloads"></textarea>
				</label>
				<label>
					최대 스캔 파일 수:
					<input type="number" bind:value={settings.max_files_per_scan} min="1000" step="1000" />
				</label>
			</section>

			<section>
				<h2>중복 탐지 설정</h2>
				<label>
					pHash 중복 임계값 (0-64, 낮을수록 엄격):
					<input type="number" bind:value={settings.phash_duplicate_threshold} min="0" max="64" step="1" />
				</label>
			</section>

			<section>
				<h2>유사도 검색 설정</h2>
				<label>
					CLIP 배치 크기 (GPU 메모리에 따라 조정):
					<input type="number" bind:value={settings.clip_batch_size} min="1" max="256" step="1" />
				</label>
				<label>
					<input type="checkbox" bind:checked={settings.clip_use_gpu} />
					GPU 사용
				</label>
				<label>
					FAISS 유사도 임계값 (0.0-1.0):
					<input type="number" bind:value={settings.faiss_similarity_threshold} min="0" max="1" step="0.01" />
				</label>
			</section>

			<section>
				<h2>클러스터링 설정</h2>
				<label>
					클러스터 시간 간격 (분):
					<input type="number" bind:value={settings.cluster_gap_minutes} min="1" max="1440" step="1" />
				</label>
			</section>

			<section>
				<h2>파일 정리 설정</h2>
				<label>
					목표 폴더 루트:
					<input type="text" bind:value={settings.target_root_folder} placeholder="D:\정리" />
				</label>
				<label>
					<input type="checkbox" bind:checked={settings.use_trash} />
					삭제 시 휴지통 사용
				</label>
			</section>

			<section>
				<h2>워커 설정</h2>
				<label>
					CLI 최대 워커 수:
					<input type="number" bind:value={settings.cli_max_workers} min="1" max="8" step="1" />
				</label>
				<label>
					CLI 타임아웃 (초):
					<input type="number" bind:value={settings.cli_timeout_seconds} min="10" max="300" step="5" />
				</label>
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
	textarea { font-family: inherit; }
	.actions { text-align: center; }
	button { padding: 0.75rem 2rem; background: #007bff; color: white; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; }
	button:disabled { background: #ccc; }
	button:hover:not(:disabled) { background: #0056b3; }
</style>
