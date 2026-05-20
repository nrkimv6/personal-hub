<script lang="ts">
	import { Button } from '$lib/components/ui';
	import type { LLMProfileConfig, LLMScheduleProfilePolicyItem } from '$lib/api';
	import {
		formatPolicyScope,
		formatPolicyWindows,
		getPolicyBlockReasonLabel,
		policyEngines,
		profileOptionsForEngine
	} from '../helpers';
	import type { LlmPolicyForm } from '../types';

	interface Props {
		profilePolicies: LLMScheduleProfilePolicyItem[];
		policyProfiles: LLMProfileConfig[];
		policyLoading: boolean;
		policySaving: boolean;
		policyError: string | null;
		policyForm: LlmPolicyForm;
		onRefresh: () => void | Promise<void>;
		onAddPolicy: () => void | Promise<void>;
		onRemovePolicy: (policy: LLMScheduleProfilePolicyItem) => void | Promise<void>;
	}

	let {
		profilePolicies,
		policyProfiles,
		policyLoading,
		policySaving,
		policyError,
		policyForm = $bindable(),
		onRefresh,
		onAddPolicy,
		onRemovePolicy
	}: Props = $props();

	function ensurePolicyFormProfile() {
		const options = profileOptionsForEngine(policyProfiles, policyForm.engine);
		if (!policyForm.profile_name && options.length > 0) {
			policyForm.profile_name = options[0].name;
		}
	}
</script>

<div class="space-y-4">
	<div class="flex items-center justify-between gap-3">
		<div>
			<h3 class="text-base font-semibold text-foreground">Schedule x Profile 정책</h3>
			<p class="text-sm text-muted-foreground">target_type 별로 허용할 profile과 시간대를 지정합니다.</p>
		</div>
		<Button variant="secondary" size="sm" onclick={onRefresh} disabled={policyLoading}>
			{policyLoading ? '로딩 중...' : '새로고침'}
		</Button>
	</div>

	{#if policyError}
		<div class="rounded-lg border border-error/30 bg-error-light px-4 py-3 text-sm text-error">
			{policyError}
		</div>
	{/if}

	<div class="card p-5">
		<div class="grid gap-4 md:grid-cols-5">
			<div>
				<label for="llm-policy-target-type" class="block text-sm font-medium text-foreground mb-1">target_type</label>
				<input id="llm-policy-target-type" type="text" bind:value={policyForm.target_type} class="w-full px-3 py-2 border border-border rounded-lg" />
			</div>
			<div>
				<label for="llm-policy-engine" class="block text-sm font-medium text-foreground mb-1">Engine</label>
				<select id="llm-policy-engine" bind:value={policyForm.engine} onchange={() => { policyForm.profile_name = ''; ensurePolicyFormProfile(); }} class="w-full px-3 py-2 border border-border rounded-lg">
					{#each policyEngines(policyProfiles, policyForm.engine) as engine}
						<option value={engine}>{engine}</option>
					{/each}
				</select>
			</div>
			<div>
				<label for="llm-policy-profile" class="block text-sm font-medium text-foreground mb-1">Profile</label>
				<select id="llm-policy-profile" bind:value={policyForm.profile_name} class="w-full px-3 py-2 border border-border rounded-lg">
					{#each profileOptionsForEngine(policyProfiles, policyForm.engine) as profile}
						<option value={profile.name}>{profile.name}</option>
					{/each}
				</select>
			</div>
			<div>
				<label for="llm-policy-priority" class="block text-sm font-medium text-foreground mb-1">Priority</label>
				<input id="llm-policy-priority" type="number" bind:value={policyForm.priority} class="w-full px-3 py-2 border border-border rounded-lg" />
			</div>
			<div class="flex items-end">
				<label class="flex items-center gap-2 text-sm text-foreground">
					<input type="checkbox" bind:checked={policyForm.enabled} class="h-4 w-4" />
					사용
				</label>
			</div>
		</div>

		<div class="mt-4 grid gap-4 md:grid-cols-2">
			<div>
				<label for="llm-policy-allowed-windows" class="block text-sm font-medium text-foreground mb-1">허용 window</label>
				<textarea id="llm-policy-allowed-windows" bind:value={policyForm.allowed_windows_text} rows="3" placeholder="09:00-18:00 1,2,3,4,5" class="w-full px-3 py-2 border border-border rounded-lg resize-none"></textarea>
			</div>
			<div>
				<label for="llm-policy-quiet-windows" class="block text-sm font-medium text-foreground mb-1">차단 window</label>
				<textarea id="llm-policy-quiet-windows" bind:value={policyForm.quiet_windows_text} rows="3" placeholder="00:00-06:00" class="w-full px-3 py-2 border border-border rounded-lg resize-none"></textarea>
			</div>
		</div>

		<div class="mt-4 flex justify-end">
			<Button variant="primary" size="sm" onclick={onAddPolicy} disabled={policySaving || policyLoading}>
				{policySaving ? '저장 중...' : '정책 추가/갱신'}
			</Button>
		</div>
	</div>

	<div class="card overflow-hidden">
		<table class="w-full text-sm">
			<thead class="bg-muted/50 text-muted-foreground">
				<tr>
					<th class="px-4 py-3 text-left font-medium">Scope</th>
					<th class="px-4 py-3 text-left font-medium">Engine/Profile</th>
					<th class="px-4 py-3 text-left font-medium">상태</th>
					<th class="px-4 py-3 text-left font-medium">Windows</th>
					<th class="px-4 py-3 text-right font-medium">작업</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#if policyLoading}
					<tr>
						<td colspan="5" class="px-4 py-6 text-center text-muted-foreground">정책 로딩 중...</td>
					</tr>
				{:else if profilePolicies.length === 0}
					<tr>
						<td colspan="5" class="px-4 py-6 text-center text-muted-foreground">등록된 정책이 없습니다.</td>
					</tr>
				{:else}
					{#each profilePolicies as policy}
						<tr>
							<td class="px-4 py-3 font-medium text-foreground">{formatPolicyScope(policy)}</td>
							<td class="px-4 py-3 text-muted-foreground">{policy.engine}/{policy.profile_name}</td>
							<td class="px-4 py-3">
								<span class="rounded-full px-2 py-1 text-xs {policy.enabled ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">
									{policy.enabled ? '사용' : getPolicyBlockReasonLabel('schedule_policy_off')}
								</span>
								<span class="ml-2 text-xs text-muted-foreground">P{policy.priority}</span>
							</td>
							<td class="px-4 py-3 text-muted-foreground">
								<div>허용: {formatPolicyWindows(policy.allowed_windows)}</div>
								<div>차단: {formatPolicyWindows(policy.quiet_windows)}</div>
							</td>
							<td class="px-4 py-3 text-right">
								<Button variant="ghost" size="sm" onclick={() => onRemovePolicy(policy)} disabled={policySaving}>
									삭제
								</Button>
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>
</div>
