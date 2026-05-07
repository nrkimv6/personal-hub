import type { ResultSegment } from './log-types';
import { normalizeLogText } from './log-parse';

export const PREVIEW_LINE_LIMIT = 3;
export const PREVIEW_CHAR_LIMIT = 600;
export const MAX_RENDER_CHARS = 8 * 1024;

interface RenderMessageOptions {
	previewMode: boolean;
	maxLines?: number;
}

export function getRenderableText(message: string): string {
	const normalized = normalizeLogText(message);
	if (normalized.length <= MAX_RENDER_CHARS) return normalized;
	const hiddenChars = normalized.length - MAX_RENDER_CHARS;
	return `${normalized.slice(0, MAX_RENDER_CHARS)}\n… ${hiddenChars} chars truncated`;
}

export function parseResultSegments(message: string): ResultSegment[] {
	const normalized = normalizeLogText(message);
	const markerPattern = /(\d+)→/g;
	const markers = [...normalized.matchAll(markerPattern)];
	if (markers.length === 0) return [];

	return markers.map((marker, index) => {
		const markerIndex = marker.index ?? 0;
		const nextMarkerIndex = markers[index + 1]?.index ?? normalized.length;
		const textStart = markerIndex + marker[0].length;
		let text = normalized.slice(textStart, nextMarkerIndex);
		if (text.startsWith(' ')) text = text.slice(1);
		return { num: marker[1], text };
	});
}

export function getPreviewLines(message: string, maxLines: number = PREVIEW_LINE_LIMIT): string {
	const renderable = getRenderableText(message);
	const parts = renderable.split('\n');
	const linePreview = parts.slice(0, maxLines).join('\n');
	if (parts.length <= maxLines && linePreview.length > PREVIEW_CHAR_LIMIT) {
		return `${linePreview.slice(0, PREVIEW_CHAR_LIMIT)}…`;
	}
	return linePreview;
}

export function getHiddenLineCount(message: string, maxLines: number = PREVIEW_LINE_LIMIT): number {
	const normalized = normalizeLogText(message);
	const count = normalized.split('\n').length;
	return Math.max(0, count - maxLines);
}

export function getHiddenCharCount(message: string): number {
	const normalized = normalizeLogText(message);
	return Math.max(0, normalized.length - PREVIEW_CHAR_LIMIT);
}

export function shouldCollapseMessage(message: string, previewCollapsedEnabled: boolean): boolean {
	if (!previewCollapsedEnabled) return false;
	return getHiddenLineCount(message) > 0 || getHiddenCharCount(message) > 0;
}

export function getExpandLabel(message: string): string {
	const hiddenLines = getHiddenLineCount(message);
	const hiddenChars = getHiddenCharCount(message);
	const parts: string[] = [];
	if (hiddenLines > 0) parts.push(`+${hiddenLines} lines`);
	if (hiddenChars > 0) parts.push(`+${hiddenChars} chars`);
	return parts.length > 0 ? `… 더보기 (${parts.join(', ')})` : '… 더보기';
}

export function renderMessage(message: string, opts: RenderMessageOptions): string {
	if (opts.previewMode) return getPreviewLines(message, opts.maxLines);
	return getRenderableText(message);
}

export function isFailureResultBody(message: string): boolean {
	const lower = normalizeLogText(message).toLowerCase();
	return (
		lower.includes('(empty aggregated_output)') ||
		lower.includes('positional parameter') ||
		lower.includes('error parsing glob') ||
		lower.includes('not recognized') ||
		lower.includes('os error') ||
		lower.includes('traceback') ||
		lower.includes('[error]')
	);
}
