import type {
	LLMScheduleProfilePolicyWindow
} from '$lib/api';

export type LlmTabId =
	| 'queue'
	| 'history'
	| 'create'
	| 'profilePolicy'
	| 'performance'
	| 'claude-sessions';

export interface LlmPreset {
	label: string;
	caller_type?: string;
	caller_id_prefix?: string;
	queue_name?: string;
	provider?: string;
	model?: string;
	cliOptions?: Record<string, unknown>;
	promptPrefix?: string;
	userPromptPlaceholder?: string;
}

export interface LlmCreateForm {
	caller_type: string;
	caller_id: string;
	prompt: string;
	queue_name: string;
	requested_by: string;
	request_source: string;
	provider: string;
	model: string;
	cli_options?: Record<string, unknown>;
	userInput: string;
}

export interface LlmPolicyForm {
	target_type: string;
	engine: string;
	profile_name: string;
	enabled: boolean;
	priority: number;
	allowed_windows_text: string;
	quiet_windows_text: string;
}

export interface LlmPendingPauseInfo {
	label: string;
	title: string;
	tone: 'quota' | 'window';
}

export type LlmPolicyWindow = LLMScheduleProfilePolicyWindow;
