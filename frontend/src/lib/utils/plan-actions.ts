import { openFile } from '$lib/api/fileSearch';

export interface PlanActionTarget {
	file_path: string;
	file_removed?: boolean;
	title?: string | null;
}

export function getPlanFileName(filePath: string): string {
	return filePath.split(/[\\/]/).pop() || filePath;
}

export function getPlanFolderPath(filePath: string): string {
	const lastSeparator = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
	return lastSeparator >= 0 ? filePath.slice(0, lastSeparator) : filePath;
}

export function getPlanDisplayName(plan: PlanActionTarget): string {
	return plan.title || getPlanFileName(plan.file_path);
}

export function getPlanActionDisabledReason(plan: PlanActionTarget): string | null {
	return plan.file_removed ? '파일이 디스크에 없습니다.' : null;
}

export async function copyPlanPath(filePath: string): Promise<void> {
	await navigator.clipboard.writeText(filePath);
}

export async function openPlanInEditor(filePath: string): Promise<void> {
	await openFile(filePath);
}

export async function openPlanInExplorer(filePath: string): Promise<string> {
	const folderPath = getPlanFolderPath(filePath);
	await navigator.clipboard.writeText(folderPath);
	return folderPath;
}
