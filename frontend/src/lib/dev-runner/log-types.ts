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
}

export interface ResultSegment {
	num: string;
	text: string;
}

export interface LogLineStyle {
	text: string;
	bg: string;
}
