import type { LogLineStyle } from './log-types';

export const FILTERABLE_TAGS = ['ERROR', 'STDERR'];

export const tagColors: Record<string, LogLineStyle> = {
	AI: { text: 'text-blue-400', bg: 'bg-blue-500/20' },
	TOOL: { text: 'text-yellow-700', bg: 'bg-yellow-900/20' },
	DONE: { text: 'text-green-400', bg: 'bg-green-500/20' },
	RESULT: { text: 'text-emerald-700', bg: 'bg-emerald-900/20' },
	ERROR: { text: 'text-red-400', bg: 'bg-red-500/20' },
	FAILURE: { text: 'text-red-300', bg: 'bg-red-600/38' },
	HOLD: { text: 'text-yellow-300', bg: 'bg-yellow-600/20' },
	INFO: { text: 'text-gray-500', bg: 'bg-transparent' },
	SYSTEM: { text: 'text-purple-400', bg: 'bg-purple-500/20' },
	WARN: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
	STDERR: { text: 'text-red-400', bg: 'bg-red-500/30' },
	LINE: { text: 'text-gray-600', bg: 'bg-transparent' },
	DIAG: { text: 'text-cyan-400', bg: 'bg-cyan-500/20' },
	THINK: { text: 'text-violet-400', bg: 'bg-violet-500/20' },
	PHASE: { text: 'text-indigo-400', bg: 'bg-indigo-500/20' },
	TRACK: { text: 'text-purple-400', bg: 'bg-purple-500/20' },
	CYCLE: { text: 'text-white', bg: 'bg-gray-600' },
	MERGE: { text: 'text-teal-400', bg: 'bg-teal-500/20' },
	COMMIT: { text: 'text-green-400', bg: 'bg-green-500/20' },
	TEST: { text: 'text-cyan-400', bg: 'bg-cyan-500/20' },
	SKIP: { text: 'text-gray-500', bg: 'bg-gray-500/20' },
	GIT: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
	BATCH: { text: 'text-teal-400', bg: 'bg-teal-500/20' },
	NOISE: { text: 'text-gray-600', bg: 'bg-gray-700/20' }
};

export function getTagStyle(tag: string): LogLineStyle {
	return tagColors[tag] ?? tagColors.INFO;
}
