import type { ParsedLine } from './log-types';

export const SEPARATOR_PATTERN = '════════════════';
export const LINE_PATTERN = /^\s*\[?(\d{2}:\d{2}:\d{2})\]?\s*\[(\w+)\]\s*(.*)/;
export const DIAG_PATTERN = /^\[(\w+)\]\s*(.*)/;
export const MERGE_TAG_PATTERN = /^\[MERGE\]\[(\w+)\]\s*(.*)/;
export const WRAPPER_PREFIX_PATTERN = /^\[(PR|PS):[^\]]+\]\s*/;
export const HEADER_ONLY_TAGS = new Set(['DIAG', 'TRIGGER', 'RUN_META', 'ENV', 'START']);

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
			isStale
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
			isStale
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
		return { id: createId(tag, '', normalizedRaw), timestamp: '', tag, message, raw: normalizedRaw, isStale };
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
