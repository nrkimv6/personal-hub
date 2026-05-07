import type { BatchPlanItem, ParsedLine } from './log-types';

export class BatchTracker {
	plans = $state<BatchPlanItem[]>([]);
	doneCount = $derived(this.plans.filter((plan) => plan.status === 'done').length);

	observe(line: ParsedLine): void {
		if (line.tag !== 'BATCH') return;

		const listMatch = line.message.match(/^PLAN_LIST\s+(.+)$/);
		if (listMatch) {
			this.plans = listMatch[1].split(',').map((name) => ({
				name: name.trim(),
				status: 'pending' as const
			}));
			return;
		}

		const startMatch = line.message.match(/^PLAN_START\s+(.+)$/);
		if (startMatch) {
			this.updatePlanStatus(startMatch[1].trim(), 'running');
			return;
		}

		const doneMatch = line.message.match(/^PLAN_DONE\s+(.+)$/);
		if (doneMatch) {
			this.updatePlanStatus(doneMatch[1].trim(), 'done');
		}
	}

	reset(): void {
		this.plans = [];
	}

	private updatePlanStatus(name: string, status: BatchPlanItem['status']): void {
		this.plans = this.plans.map((plan) => (plan.name === name ? { ...plan, status } : plan));
	}
}
