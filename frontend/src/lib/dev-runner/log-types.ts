export interface BatchPlanItem {
	name: string;
	status: 'pending' | 'running' | 'done';
}

export interface ParsedLine {
	id: string;
	timestamp: string;
	tag: string;
	message: string;
	raw: string;
	isStale: boolean;
	noiseCount?: number;
	structured?: StructuredLogEvent;
}

export type StructuredLogKind = 'tool_call' | 'tool_result' | 'phase' | 'failure' | 'tagged_log';
export type StructuredLogSeverity = 'info' | 'warn' | 'error';
export type FailureClassification =
	| 'retryable'
	| 'approval_required'
	| 'environment'
	| 'product';

export interface StructuredArtifact {
	path: string;
	display_path: string;
	allowed: boolean;
	reason: 'allowed_evidence_root' | 'disallowed_artifact_root';
}

export interface StructuredLogEvent {
	schema_version: 1;
	event_id?: string;
	kind: StructuredLogKind;
	source?: 'dev_runner_log' | 'history_log' | 'ui_parser';
	severity?: StructuredLogSeverity;
	tag: string;
	message: string;
	raw: string;
	timestamp?: string;
	name?: string;
	args_summary?: string;
	line_count?: number;
	artifact?: StructuredArtifact | null;
	artifacts?: StructuredArtifact[];
	result?: {
		status: 'success' | 'failure' | 'unknown';
		output_schema: {
			format: 'text';
			line_count: number;
			empty: boolean;
		};
	};
	failure?: {
		classification: FailureClassification;
	};
	display?: {
		compact: boolean;
	};
	replay?: {
		eligible: boolean;
		reason: string;
	};
}

export interface EventLineObjectPayload {
	text: string;
	meta?: Record<string, unknown>;
	structured_event?: StructuredLogEvent;
}

export type EventLinePayload = string | EventLineObjectPayload;

export interface ResultSegment {
	num: string;
	text: string;
}

export interface LogLineStyle {
	text: string;
	bg: string;
}
