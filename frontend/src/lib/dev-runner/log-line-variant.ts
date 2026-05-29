import type { ParsedLine } from './log-types';

export type LogLineVariant = 'default' | 'phase' | 'tool' | 'cycle' | 'result';

export interface LogLineVariantInfo {
	variant: LogLineVariant;
	containerClass: string;
	bodyClass: string;
	timestampClass?: string;
	badgeWrapperClass?: string;
	title?: string;
}

interface VariantOptions {
	resultFailure?: boolean;
}

export function getLogLineVariant(line: ParsedLine, opts: VariantOptions = {}): LogLineVariantInfo {
	const structuredFailure = Boolean(line.structured?.failure);
	const structuredSeverity = line.structured?.severity;
	if (line.tag === 'CYCLE') {
		return {
			variant: 'cycle',
			containerClass: `phase-separator ${line.isStale ? 'opacity-30' : ''}`,
			bodyClass: 'font-mono text-[10px] text-muted-foreground whitespace-pre-wrap'
		};
	}
	if (line.tag === 'PHASE') {
		return {
			variant: 'phase',
			containerClass: `dr-log-line dr-log-line-phase flex items-start gap-2 py-0 leading-5 mt-1.5 border-t border-indigo-900/40 ${line.isStale ? 'opacity-30' : ''}`,
			bodyClass: 'flex-1 min-w-0 break-all text-indigo-300 font-medium whitespace-pre-wrap'
		};
	}
	if (line.tag === 'TOOL') {
		return {
			variant: 'tool',
			containerClass: `dr-log-line dr-log-line-tool flex items-start gap-2 py-0 leading-5 ${structuredSeverity === 'error' ? 'opacity-100 bg-red-950/25 border-l-2 border-red-700 -mx-1 px-1 rounded' : 'opacity-40'} ${line.isStale ? 'opacity-20' : ''}`,
			timestampClass: 'text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none',
			bodyClass: 'flex-1 min-w-0 break-all whitespace-pre-wrap text-gray-500'
		};
	}
	if (line.tag === 'RESULT') {
		const resultFailure = opts.resultFailure || structuredFailure || line.structured?.result?.status === 'failure';
		return {
			variant: 'result',
			containerClass: `dr-log-line dr-log-line-result flex items-start gap-0 py-0 leading-5 ${resultFailure ? 'opacity-100 bg-red-950/35 border-l-2 border-red-500 -mx-1 px-1 rounded' : 'opacity-60'} ${line.isStale ? 'opacity-20' : ''}`,
			timestampClass: 'text-xs text-gray-600 shrink-0 w-[56px] tabular-nums select-none text-right pr-1',
			badgeWrapperClass: 'mr-1',
			bodyClass: 'flex-1 min-w-0'
		};
	}

	return {
		variant: 'default',
		containerClass: `dr-log-line dr-log-line-${line.tag.toLowerCase()} flex items-start gap-2 py-0 leading-5 ${line.isStale ? 'opacity-30' : ''} ${line.tag === 'FAILURE' ? 'bg-red-950/70 border-l-2 border-red-500 -mx-3 px-3 rounded' : line.tag === 'HOLD' ? 'bg-yellow-950/40 border-l-2 border-yellow-500 -mx-3 px-3 rounded' : line.tag === 'ERROR' || structuredFailure ? 'bg-red-950/50 -mx-3 px-3 rounded' : ''}`,
		bodyClass: `flex-1 min-w-0 break-all whitespace-pre-wrap ${line.tag === 'HOLD' ? 'text-yellow-300 font-bold' : line.tag === 'FAILURE' || structuredFailure ? 'text-red-300 font-bold' : line.tag === 'ERROR' ? 'text-red-400' : line.tag === 'DONE' ? 'text-green-400' : 'text-gray-300'}`,
		title: line.tag === 'DONE' ? 'LLM call done; runner completion is reported by the completed event' : undefined
	};
}
