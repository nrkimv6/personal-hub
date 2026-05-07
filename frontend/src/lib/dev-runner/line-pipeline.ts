import type { BatchTracker } from './batch-tracker.svelte';
import type { ParsedLine } from './log-types';

export interface LinePipelineContext {
	isStale: boolean;
	hasSeparator(raw: string): boolean;
	markExistingLinesStale(): void;
	getPendingStale(): boolean;
	setPendingStale(value: boolean): void;
	showNoiseIndicator(): void;
	hideNoiseIndicator(): void;
	batchTracker: BatchTracker;
	showFailureBanner(message: string): void;
}

export type LineHandler = (line: ParsedLine, ctx: LinePipelineContext) => void;

export const staleMarkingHandler: LineHandler = (line, ctx) => {
	if (!ctx.isStale && ctx.hasSeparator(line.raw)) {
		if (ctx.getPendingStale()) {
			ctx.markExistingLinesStale();
		}
		ctx.setPendingStale(true);
	}
};

export const noiseIndicatorHandler: LineHandler = (line, ctx) => {
	if (ctx.isStale) return;
	if (line.tag === 'NOISE') {
		ctx.showNoiseIndicator();
	} else {
		ctx.hideNoiseIndicator();
	}
};

export const batchTrackingHandler: LineHandler = (line, ctx) => {
	if (!ctx.isStale) {
		ctx.batchTracker.observe(line);
	}
};

export const separatorResetHandler: LineHandler = (line, ctx) => {
	if (!ctx.isStale && ctx.hasSeparator(line.raw)) {
		ctx.batchTracker.reset();
	}
};

export const failureBannerHandler: LineHandler = (line, ctx) => {
	if (!ctx.isStale && line.tag === 'FAILURE') {
		ctx.showFailureBanner(line.message);
	}
};

export const defaultLineHandlers: LineHandler[] = [
	staleMarkingHandler,
	noiseIndicatorHandler,
	batchTrackingHandler,
	separatorResetHandler,
	failureBannerHandler
];
