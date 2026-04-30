<script lang="ts">
	import { Copy, ExternalLink, FolderOpen } from 'lucide-svelte';
	import type { CurrentTrackingResponse } from '$lib/api/dev-runner';
	import { toast } from '$lib/stores/toast';
	import {
		copyPlanPath,
		getPlanFileName,
		openPlanInEditor,
		openPlanInExplorer
	} from '$lib/utils/plan-actions';

	interface Props {
		tracking: CurrentTrackingResponse | null;
	}

	let { tracking }: Props = $props();

	// confidence별 색상
	function badgeClass(confidence: string, stale: boolean): string {
		if (stale) return 'text-muted-foreground bg-muted border border-border';
		if (confidence === 'HIGH') return 'text-success bg-success/10 border border-success/20';
		if (confidence === 'MEDIUM') return 'text-warning bg-warning/10 border border-warning/20';
		return 'text-muted-foreground bg-muted border border-border';
	}

	function labelText(confidence: string, stale: boolean): string {
		if (stale) return 'STALE';
		return confidence;
	}

	async function handleCopyPlanPath(filePath: string) {
		try {
			await copyPlanPath(filePath);
			toast.success('계획서 경로를 복사했습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '계획서 경로 복사 실패');
		}
	}

	async function handleOpenPlanInEditor(filePath: string) {
		try {
			await openPlanInEditor(filePath);
			toast.success('VSCode에서 계획서를 여는 요청을 보냈습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '계획서 열기 실패');
		}
	}

	async function handleOpenPlanInExplorer(filePath: string) {
		try {
			await openPlanInExplorer(filePath);
			toast.success('계획서 폴더 경로를 복사했습니다.');
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '계획서 폴더 경로 복사 실패');
		}
	}
</script>

{#if tracking}
	<div class="bg-card rounded-md border border-primary/20 px-3 py-2">
		<div class="mb-1 flex items-center gap-2">
			<svg class="w-3 h-3 text-primary" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10"/>
				<circle cx="12" cy="12" r="6"/>
				<circle cx="12" cy="12" r="2"/>
			</svg>
			<span class="text-[10px] font-mono font-bold uppercase text-purple-600 dark:text-purple-400">Tracking</span>
			<span
				class="rounded px-1.5 py-0.5 text-[10px] font-mono font-bold {badgeClass(tracking.confidence, tracking.stale)}"
			>
				{labelText(tracking.confidence, tracking.stale)}
			</span>
			{#if tracking.line_num != null}
				<span class="text-[10px] font-mono text-muted-foreground">L{tracking.line_num}</span>
			{/if}
			{#if tracking.stale}
				<span class="text-[10px] font-mono text-muted-foreground/60">· stale</span>
			{/if}
		</div>
		<p class="truncate text-sm font-medium text-foreground" title={tracking.text}>
			{tracking.text}
		</p>
		{#if tracking.plan_file}
			<div class="mt-1 rounded border border-border/70 bg-muted/30 px-2 py-1.5">
				<p class="truncate text-xs text-muted-foreground font-mono" title={tracking.plan_file}>
					{getPlanFileName(tracking.plan_file)}
				</p>
				<div class="mt-1 flex flex-wrap gap-1">
					<button
						type="button"
						class="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground"
						onclick={() => handleCopyPlanPath(tracking.plan_file!)}
						title="계획서 경로 복사"
					>
						<Copy size={11} /> 복사
					</button>
					<button
						type="button"
						class="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground"
						onclick={() => handleOpenPlanInEditor(tracking.plan_file!)}
						title="VSCode에서 열기"
					>
						<ExternalLink size={11} /> 열기
					</button>
					<button
						type="button"
						class="inline-flex items-center gap-1 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground"
						onclick={() => handleOpenPlanInExplorer(tracking.plan_file!)}
						title="계획서 폴더 경로 복사"
					>
						<FolderOpen size={11} /> 폴더
					</button>
				</div>
			</div>
		{/if}
	</div>
{/if}
