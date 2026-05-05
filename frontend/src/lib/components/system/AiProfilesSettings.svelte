<script lang="ts">
	import { onMount } from 'svelte';
	import { llmApi, type LLMProfileConfig, type LLMProfileStatusItem, type LLMProfilesResponse } from '$lib/api/system';
	import { toast } from '$lib/stores/toast';
	import { Plus, Trash2, Terminal, Check } from 'lucide-svelte';

	let loading = $state(true);
	let saving = $state(false);
	let launchingKey = $state('');
	let data = $state<LLMProfilesResponse | null>(null);
	let drafts = $state<LLMProfileConfig[]>([]);
	let profileStatuses = $state<LLMProfileStatusItem[]>([]);
	let selectedDraft = $state<Record<string, string>>({});
	let workerRestartBanner = $state(false);

	// Gemini config_dir env key 미지원 여부 (서버의 ENGINE_ENV_KEYS 기준, 현재 null)
	const GEMINI_CONFIG_DIR_UNSUPPORTED = true;

	onMount(async () => {
		try {
			data = await llmApi.listProfiles();
			profileStatuses = await llmApi.getProfileStatus();
			drafts = data.profiles.map((p) => ({ ...p, extra_env: { ...p.extra_env } }));
			selectedDraft = { ...data.selected };
		} catch (e) {
			toast.error('AI 프로필 로드 실패');
		} finally {
			loading = false;
		}
	});

	function addProfile(engine: string) {
		drafts = [
			...drafts,
			{
				engine,
				name: '',
				config_dir: null,
				extra_env: {},
				enabled: true,
				priority: 0
			}
		];
	}

	function removeProfile(idx: number) {
		const p = drafts[idx];
		if (p.name && selectedDraft[p.engine] === p.name) {
			// selected 였으면 default 로 fallback
			const remaining = drafts.filter((d, i) => i !== idx && d.engine === p.engine);
			selectedDraft[p.engine] =
				remaining.find((r) => r.name === 'default')?.name ?? remaining[0]?.name ?? 'default';
		}
		drafts = drafts.filter((_, i) => i !== idx);
	}

	async function save() {
		saving = true;
		try {
			const updated = await llmApi.updateProfiles({
				selected: selectedDraft,
				profiles: drafts
			});
			data = updated;
			profileStatuses = await llmApi.getProfileStatus();
			drafts = updated.profiles.map((p) => ({ ...p, extra_env: { ...p.extra_env } }));
			selectedDraft = { ...updated.selected };
			workerRestartBanner = true;
			toast.success('AI 프로필 저장됨');
		} catch (e: unknown) {
			const detail = (e as { detail?: string })?.detail ?? String(e);
			toast.error(`저장 실패: ${detail}`);
		} finally {
			saving = false;
		}
	}

	async function launchCli(engine: string, name: string) {
		const key = `${engine}/${name}`;
		launchingKey = key;
		try {
			const resp = await llmApi.launchCli(engine, name);
			if (resp?.status === 'timeout') {
				toast.warning('명령 전송됨, 리스너 응답 없음 — listener 실행 확인 필요');
			} else if (resp?.status === 'redis_unavailable') {
				toast.error(`Redis 연결 없음. ${resp.message ?? '수동 실행 필요'}`);
			} else {
				toast.success(`새 콘솔에서 ${engine} CLI 실행됨 — 로그인 후 창 닫기`);
			}
		} catch (e) {
			toast.error(`CLI 실행 실패: ${String(e)}`);
		} finally {
			launchingKey = '';
		}
	}

	function profilesForEngine(engine: string) {
		return drafts.map((p, i) => ({ ...p, idx: i })).filter((p) => p.engine === engine);
	}

	function statusFor(engine: string, name: string) {
		return profileStatuses.find((s) => s.engine === engine && s.profile_name === name);
	}

	async function pauseProfile(engine: string, name: string) {
		await llmApi.pauseProfile(engine, name);
		profileStatuses = await llmApi.getProfileStatus();
		toast.success(`${engine}/${name} 일시중지됨`);
	}

	async function resumeProfile(engine: string, name: string) {
		await llmApi.resumeProfile(engine, name);
		profileStatuses = await llmApi.getProfileStatus();
		toast.success(`${engine}/${name} 재개됨`);
	}

	function isConfigDirDisabled(engine: string) {
		return engine === 'gemini' && GEMINI_CONFIG_DIR_UNSUPPORTED;
	}
</script>

<div class="space-y-6">
	{#if workerRestartBanner}
		<div class="rounded-md bg-blue-50 border border-blue-200 px-4 py-3 text-sm text-blue-800 flex justify-between items-start">
			<span>변경사항은 다음 LLM 요청부터 적용됩니다. 즉시 반영하려면 워커를 재시작하세요.</span>
			<button onclick={() => (workerRestartBanner = false)} class="ml-4 text-blue-500 hover:text-blue-700 text-xs">닫기</button>
		</div>
	{/if}

	{#if loading}
		<p class="text-sm text-muted-foreground">로딩 중...</p>
	{:else if data}
		{#each data.supported_engines as engine}
			<section>
				<div class="flex items-center justify-between mb-3">
					<h3 class="font-semibold text-sm capitalize">{engine}</h3>
					<button
						onclick={() => addProfile(engine)}
						class="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
					>
						<Plus size={14} />프로필 추가
					</button>
				</div>

				<div class="space-y-2">
					{#each profilesForEngine(engine) as p (p.idx)}
						<div class="rounded-md border border-border bg-card p-3 space-y-2">
							<div class="flex items-center gap-3">
								{@const status = statusFor(engine, p.name)}
								<!-- 선택 라디오 -->
								<input
									type="radio"
									name="selected-{engine}"
									checked={selectedDraft[engine] === p.name}
									onchange={() => (selectedDraft[engine] = p.name)}
									class="mt-0.5"
									title="이 프로필 선택"
								/>
								<!-- 이름 -->
								<input
									type="text"
									bind:value={drafts[p.idx].name}
									placeholder="프로필 이름 (예: work, personal)"
									class="flex-1 text-sm border border-border rounded px-2 py-1 bg-background"
								/>
								<label class="flex items-center gap-1 text-xs text-muted-foreground">
									<input type="checkbox" bind:checked={drafts[p.idx].enabled} />
									활성
								</label>
								<input
									type="number"
									bind:value={drafts[p.idx].priority}
									class="w-20 text-xs border border-border rounded px-2 py-1 bg-background"
									title="라우팅 우선순위"
								/>
								<span class="text-xs px-2 py-1 rounded bg-muted text-muted-foreground">
									{status?.state ?? (p.enabled === false ? 'disabled' : 'available')}
								</span>
								{#if status?.state === 'paused_by_quota'}
									<button
										onclick={() => resumeProfile(engine, p.name)}
										class="text-xs px-2 py-1 rounded border border-border hover:bg-muted"
									>
										재개
									</button>
								{:else if p.name}
									<button
										onclick={() => pauseProfile(engine, p.name)}
										class="text-xs px-2 py-1 rounded border border-border hover:bg-muted"
									>
										일시중지
									</button>
								{/if}
								<!-- CLI 직접 실행 -->
								<button
									onclick={() => launchCli(engine, p.name)}
									disabled={!p.name || launchingKey === `${engine}/${p.name}`}
									class="flex items-center gap-1 text-xs px-2 py-1 rounded border border-border hover:bg-muted disabled:opacity-40"
									title="해당 프로필 환경으로 CLI 실행 (로그인 목적)"
								>
									<Terminal size={13} />
									{launchingKey === `${engine}/${p.name}` ? '실행 중...' : 'CLI 실행'}
								</button>
								<!-- 삭제 -->
								<button
									onclick={() => removeProfile(p.idx)}
									class="text-red-500 hover:text-red-700 p-1"
									title="삭제"
								>
									<Trash2 size={14} />
								</button>
							</div>

							<!-- config_dir -->
							<div class="flex items-center gap-2">
								<label class="text-xs text-muted-foreground w-24 shrink-0">Config 디렉토리</label>
								{#if isConfigDirDisabled(engine)}
									<input
										type="text"
										disabled
										placeholder="Gemini CLI는 config dir env 미지원 — extra_env 사용"
										class="flex-1 text-xs border border-border rounded px-2 py-1 bg-muted text-muted-foreground cursor-not-allowed"
										title="Gemini CLI는 config dir env를 지원하지 않아 계정 분리 불가. extra_env에 직접 설정하세요."
									/>
								{:else}
									<input
										type="text"
										bind:value={drafts[p.idx].config_dir}
										placeholder="예: C:/Users/name/.claude-work (비우면 기본값)"
										class="flex-1 text-xs border border-border rounded px-2 py-1 bg-background"
									/>
								{/if}
							</div>
						</div>
					{/each}

					{#if profilesForEngine(engine).length === 0}
						<p class="text-xs text-muted-foreground">프로필 없음 — 추가 버튼으로 생성하세요.</p>
					{/if}
				</div>
			</section>
		{/each}

		<div class="flex justify-end pt-2">
			<button
				onclick={save}
				disabled={saving}
				class="flex items-center gap-1 px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-60"
			>
				<Check size={14} />
				{saving ? '저장 중...' : '저장'}
			</button>
		</div>
	{/if}
</div>
