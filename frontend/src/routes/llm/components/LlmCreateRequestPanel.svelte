<script lang="ts">
	import type { ProviderInfo } from '$lib/api';
	import type { LlmCreateForm, LlmPreset } from '../types';
	import LlmSettingsPanel from './LlmSettingsPanel.svelte';

	interface Props {
		createForm: LlmCreateForm;
		createLoading: boolean;
		createError: string | null;
		createSuccess: boolean;
		providers: ProviderInfo[];
		providersLoading: boolean;
		providersError: string | null;
		presets: LlmPreset[];
		selectedPreset: LlmPreset;
		getProviderModels: (providerKey: string) => string[];
		onApplyPreset: (preset: LlmPreset) => void;
		onCreateRequest: () => void | Promise<void>;
		onShowQueue: () => void | Promise<void>;
	}

	let {
		createForm = $bindable(),
		createLoading,
		createError,
		createSuccess = $bindable(),
		providers,
		providersLoading,
		providersError,
		presets,
		selectedPreset = $bindable(),
		getProviderModels,
		onApplyPreset,
		onCreateRequest,
		onShowQueue
	}: Props = $props();
</script>

<div class="max-w-2xl">
	<div class="bg-white rounded-lg border border-border p-6">
		<h3 class="text-lg font-bold text-foreground mb-4">수동 LLM 요청 생성</h3>
		<p class="text-sm text-muted-foreground mb-6">테스트 또는 디버깅 목적으로 수동으로 LLM 요청을 생성합니다.</p>

		{#if createSuccess}
			<div class="mb-4 p-4 bg-success-light border border-green-200 text-success rounded-lg flex items-center justify-between">
				<span>요청이 성공적으로 생성되었습니다.</span>
				<button
					type="button"
					onclick={() => { createSuccess = false; onShowQueue(); }}
					class="text-sm underline hover:no-underline font-medium"
				>대기열에서 확인</button>
			</div>
		{/if}

		{#if createError}
			<div class="mb-4 p-4 bg-error-light border border-red-200 text-error rounded-lg">
				{createError}
			</div>
		{/if}

		<div class="space-y-4">
			<div>
				<label class="block text-sm font-medium text-foreground mb-1">프리셋</label>
				<select
					value={selectedPreset.label}
					onchange={(e) => {
						const found = presets.find(preset => preset.label === (e.target as HTMLSelectElement).value);
						if (found) onApplyPreset(found);
					}}
					class="w-full px-3 py-2 border border-border rounded-lg"
				>
					{#each presets as preset}
						<option value={preset.label}>{preset.label}</option>
					{/each}
				</select>
			</div>

			<div>
				<label class="block text-sm font-medium text-foreground mb-1">큐</label>
				<select bind:value={createForm.queue_name} class="w-full px-3 py-2 border border-border rounded-lg">
					<option value="utility">utility (일반 자동화)</option>
					<option value="system">system (시스템/개발, 우선순위 높음)</option>
				</select>
			</div>

			<div>
				<label class="block text-sm font-medium text-foreground mb-1">호출자 타입</label>
				<select bind:value={createForm.caller_type} class="w-full px-3 py-2 border border-border rounded-lg">
					<option value="test">test</option>
					<option value="instagram">instagram</option>
				</select>
			</div>

			<div>
				<label class="block text-sm font-medium text-foreground mb-1">호출자 ID *</label>
				<input
					type="text"
					bind:value={createForm.caller_id}
					placeholder="예: 123"
					class="w-full px-3 py-2 border border-border rounded-lg"
				/>
			</div>

			<LlmSettingsPanel
				bind:createForm
				{providers}
				{providersLoading}
				{providersError}
				{getProviderModels}
			/>

			{#if selectedPreset.label === '(직접 입력)'}
				<div>
					<label class="block text-sm font-medium text-foreground mb-1">프롬프트 *</label>
					<textarea
						bind:value={createForm.prompt}
						rows="6"
						placeholder="LLM에 전달할 프롬프트를 입력하세요..."
						class="w-full px-3 py-2 border border-border rounded-lg resize-none"
					></textarea>
				</div>
			{:else}
				<div>
					<textarea
						bind:value={createForm.userInput}
						rows="6"
						placeholder={selectedPreset.userPromptPlaceholder ?? '내용을 입력하세요...'}
						class="w-full px-3 py-2 border border-border rounded-lg resize-none"
					></textarea>
				</div>
			{/if}

			<div class="grid grid-cols-2 gap-4">
				<div>
					<label class="block text-sm font-medium text-foreground mb-1">요청자</label>
					<input
						type="text"
						bind:value={createForm.requested_by}
						class="w-full px-3 py-2 border border-border rounded-lg"
					/>
				</div>
				<div>
					<label class="block text-sm font-medium text-foreground mb-1">출처</label>
					<input
						type="text"
						bind:value={createForm.request_source}
						class="w-full px-3 py-2 border border-border rounded-lg"
					/>
				</div>
			</div>

			<div class="pt-4">
				<button
					onclick={onCreateRequest}
					disabled={createLoading}
					class="btn btn-primary w-full disabled:opacity-50"
				>
					{createLoading ? '생성 중...' : '요청 생성'}
				</button>
			</div>
		</div>
	</div>
</div>
