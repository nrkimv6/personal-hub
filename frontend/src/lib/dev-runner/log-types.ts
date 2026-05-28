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

export interface StructuredLogEvent {
	schema_version: 1;
	kind: 'tool_call' | 'tool_result' | 'tagged_log';
	tag: string;
	message: string;
	raw: string;
	timestamp?: string;
	name?: string;
}

export interface ResultSegment {
	num: string;
	text: string;
}

export interface LogLineStyle {
	text: string;
	bg: string;
}
