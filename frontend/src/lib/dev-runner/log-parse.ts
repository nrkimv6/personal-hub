import type { ParsedLine, StructuredLogEvent } from './log-types';

export const SEPARATOR_PATTERN = '════════════════';
export const LINE_PATTERN = /^\s*\[?(\d{2}:\d{2}:\d{2})\]?\s*\[(\w+)\]\s*(.*)/;
export const DIAG_PATTERN = /^\[(\w+)\]\s*(.*)/;
export const MERGE_TAG_PATTERN = /^\[MERGE\]\[(\w+)\]\s*(.*)/;
export const WRAPPER_PREFIX_PATTERN = /^\[(PR|PS):[^\]]+\]\s*/;
export const HEADER_ONLY_TAGS = new Set(['DIAG', 'TRIGGER', 'RUN_META', 'ENV', 'START']);
const STRUCTURED_TAGS = new Set(['TOOL', 'RESULT', 'PHASE', 'FAILURE', 'HOLD']);
const ALLOWED_ARTIFACT_PREFIXES = [
	'.tmp/codex/',
	'.tmp/codex-browser-artifacts/',
	'logs/'
] as const;
const ARTIFACT_PATTERN =
	/((?:[A-Za-z]:)?[\\/\.]?(?:[\w.-]+[\\/])+[\w .()-]+\.(?:png|jpe?g|webp|gif|jsonl?|log|txt|md))/gi;
const FAILURE_KEYWORDS: Array<[NonNullable<StructuredLogEvent['failure']>['classification'], string[]]> = [
	['approval_required', ['approval_required', 'approval required', 'manual approval', 'explicit approval']],
	['retryable', ['rate_limited', 'rate limit', 'timeout', 'timed out', 'connection reset', 'temporarily unavailable', '429', 'redis disconnected']],
	['environment', ['not recognized', 'positional parameter', 'permission denied', 'no such file', 'enoent', 'file in use', 'build lock', 'port already']],
	['product', ['traceback', 'assertionerror', 'test failed', 'failed test', '[error]', 'exception', 'os error']]
];

export type LineIdFactory = (tag: string, timestamp: string, raw: string) => string;

export function normalizeLogText(text: string): string {
	return text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

export function createLineId(sequence: number, tag: string, timestamp: string, raw: string): string {
	const seed = `${tag}|${timestamp}|${raw}`;
	let hash = 0;
	for (let i = 0; i < seed.length; i++) {
		hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
	}
	return `${sequence}-${Math.abs(hash)}`;
}

function createEventId(raw: string): string {
	let hash = 0;
	for (let i = 0; i < raw.length; i++) {
		hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
	}
	return `log_${Math.abs(hash).toString(16)}`;
}

function countLines(text: string): number {
	return text ? text.split('\n').length : 1;
}

export function classifyStructuredFailure(message: string, tag?: string): StructuredLogEvent['failure'] | undefined {
	const lower = normalizeLogText(message).toLowerCase();
	if (tag === 'FAILURE') {
		for (const [classification, tokens] of FAILURE_KEYWORDS) {
			if (tokens.some((token) => lower.includes(token))) return { classification };
		}
		return { classification: 'product' };
	}
	if (tag === 'HOLD') return { classification: 'approval_required' };
	for (const [classification, tokens] of FAILURE_KEYWORDS) {
		if (tokens.some((token) => lower.includes(token))) return { classification };
	}
	return undefined;
}

function classifyResultStatus(message: string, failure?: StructuredLogEvent['failure']): 'success' | 'failure' | 'unknown' {
	const lower = message.toLowerCase();
	if (/\b(?:exit|code|status)\s*[:=]\s*0\b/.test(lower) || lower.includes('success')) return 'success';
	if (failure || /\b(?:exit|code|status)\s*[:=]\s*[1-9]\d*\b/.test(lower)) return 'failure';
	return 'unknown';
}

function artifactDisplayPath(normalizedPath: string): string {
	const lower = normalizedPath.toLowerCase();
	for (const prefix of ALLOWED_ARTIFACT_PREFIXES) {
		const index = lower.indexOf(prefix);
		if (index >= 0) return normalizedPath.slice(index);
	}
	return normalizedPath;
}

export function normalizeStructuredArtifact(path: string | null | undefined): StructuredLogEvent['artifact'] {
	const rawPath = String(path ?? '').trim().replace(/^[`"'<>]+|[`"'<>.,;)]+$/g, '');
	if (!rawPath) return null;
	const normalizedPath = rawPath.replace(/\\/g, '/');
	const lower = normalizedPath.toLowerCase();
	const allowed =
		ALLOWED_ARTIFACT_PREFIXES.some((prefix) => lower.startsWith(prefix)) ||
		ALLOWED_ARTIFACT_PREFIXES.some((prefix) => lower.includes(`/${prefix}`));
	return {
		path: rawPath,
		display_path: allowed ? artifactDisplayPath(normalizedPath) : normalizedPath.split('/').pop() ?? normalizedPath,
		allowed,
		reason: allowed ? 'allowed_evidence_root' : 'disallowed_artifact_root'
	};
}

function extractStructuredArtifacts(raw: string): NonNullable<StructuredLogEvent['artifacts']> {
	const artifacts: NonNullable<StructuredLogEvent['artifacts']> = [];
	const seen = new Set<string>();
	for (const match of raw.matchAll(ARTIFACT_PATTERN)) {
		const artifact = normalizeStructuredArtifact(match[1]);
		if (!artifact) continue;
		const key = artifact.path.toLowerCase();
		if (seen.has(key)) continue;
		seen.add(key);
		artifacts.push(artifact);
	}
	return artifacts;
}

export function buildStructuredLogEvent(tag: string, timestamp: string, message: string, raw: string): StructuredLogEvent | undefined {
	if (!STRUCTURED_TAGS.has(tag)) return undefined;
	const trimmedMessage = message.trim();
	const failure = classifyStructuredFailure(trimmedMessage, tag);
	const artifacts = extractStructuredArtifacts(raw);
	const structured: StructuredLogEvent = {
		schema_version: 1,
		event_id: createEventId(raw),
		kind: tag === 'TOOL' ? 'tool_call' : tag === 'RESULT' ? 'tool_result' : tag === 'PHASE' ? 'phase' : tag === 'FAILURE' || tag === 'HOLD' ? 'failure' : 'tagged_log',
		source: 'ui_parser',
		severity: failure ? 'error' : 'info',
		tag,
		message: trimmedMessage,
		raw,
		line_count: countLines(raw),
		artifact: artifacts[0] ?? null,
		artifacts,
		display: { compact: true },
		replay: { eligible: false, reason: 'ui_log_event' }
	};
	if (timestamp) structured.timestamp = timestamp;
	if (tag === 'TOOL' && trimmedMessage) {
		const [name, ...rest] = trimmedMessage.split(/[:\s]/);
		structured.name = name;
		const argsSummary = rest.join(' ').trim();
		if (argsSummary) structured.args_summary = argsSummary.length > 180 ? `${argsSummary.slice(0, 180)}...` : argsSummary;
	}
	if (tag === 'RESULT') {
		const status = classifyResultStatus(trimmedMessage, failure);
		structured.result = {
			status,
			output_schema: {
				format: 'text',
				line_count: countLines(trimmedMessage),
				empty: trimmedMessage.length === 0
			}
		};
		if (status === 'failure') structured.severity = 'error';
	}
	if (failure) structured.failure = failure;
	return structured;
}

export function parseLine(text: string, isStale: boolean, createId: LineIdFactory): ParsedLine {
	const normalizedRaw = normalizeLogText(text);
	const [head = '', ...tail] = normalizedRaw.split('\n');
	const tailText = tail.length > 0 ? `\n${tail.join('\n')}` : '';

	const strippedHead = head.replace(WRAPPER_PREFIX_PATTERN, '');
	const finalMatch = strippedHead.match(LINE_PATTERN);
	if (finalMatch) {
		const message = `${finalMatch[3]}${tailText}`;
		return {
			id: createId(finalMatch[2], finalMatch[1], normalizedRaw),
			timestamp: finalMatch[1],
			tag: finalMatch[2],
			message,
			raw: normalizedRaw,
			isStale,
			structured: buildStructuredLogEvent(finalMatch[2], finalMatch[1], message, normalizedRaw)
		};
	}

	const mergeMatch = strippedHead.match(MERGE_TAG_PATTERN);
	if (mergeMatch) {
		const message = `${mergeMatch[2]}${tailText}`;
		return {
			id: createId(mergeMatch[1], '', normalizedRaw),
			timestamp: '',
			tag: mergeMatch[1],
			message,
			raw: normalizedRaw,
			isStale,
			structured: buildStructuredLogEvent(mergeMatch[1], '', message, normalizedRaw)
		};
	}

	const diagMatch = strippedHead.match(DIAG_PATTERN);
	if (diagMatch) {
		const tag = diagMatch[1];
		const message = `${diagMatch[2]}${tailText}`;
		if (tag === 'NOISE') {
			const noiseCount = parseInt(diagMatch[2]) || 0;
			return { id: createId(tag, '', normalizedRaw), timestamp: '', tag, message, raw: normalizedRaw, isStale, noiseCount };
		}
		return {
			id: createId(tag, '', normalizedRaw),
			timestamp: '',
			tag,
			message,
			raw: normalizedRaw,
			isStale,
			structured: buildStructuredLogEvent(tag, '', message, normalizedRaw)
		};
	}

	return {
		id: createId('', '', normalizedRaw),
		timestamp: '',
		tag: '',
		message: normalizedRaw,
		raw: normalizedRaw,
		isStale
	};
}

export function isSeparator(text: string): boolean {
	return text.includes(SEPARATOR_PATTERN);
}

export function extractSeparatorText(text: string): string {
	return text.replace(/[═=\s]+/g, ' ').trim() || '새 세션';
}

export function buildSessionSeparator(identity: string, createId: LineIdFactory): ParsedLine {
	return parseLine(`${SEPARATOR_PATTERN} new log session: ${identity} ${SEPARATOR_PATTERN}`, false, createId);
}

export function extractLogIdentity(parsed: ParsedLine[]): string | null {
	for (const line of parsed) {
		if (line.tag !== 'START') continue;
		const match = line.message.match(/\blog_path=([^\s]+)/);
		if (match) return match[1];
	}
	return null;
}
