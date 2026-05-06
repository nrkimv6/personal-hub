/**
 * planArchiveResidualState.svelte.ts
 *
 * ArchiveTab 잔류 surface 상태 — retrieval/index progress, manual analyze,
 * manual reanalyze request id/result toast payload를 컴포넌트 외부로 분리한다.
 *
 * ⚠️ .svelte.ts 확장자 필수 — $state rune 사용을 위해.
 */

import type {
  PlanArchiveRetrievalResult,
  PlanArchiveMetricsResponse,
  PlanArchiveIndexResponse,
  PlanArchiveCrossRepoIndexResponse,
  PlanArchiveAnalyzeResponse,
} from '$lib/api/plan-records';

export class ArchiveResidualState {
  // ── Retrieval filters ─────────────────────────────────────
  retrievalQ = $state('');
  retrievalPath = $state('');
  retrievalRepoKey = $state('');
  retrievalCategory = $state('');
  retrievalTags = $state('');
  retrievalIntent = $state('');
  retrievalScope = $state('');
  retrievalDateFrom = $state('');
  retrievalDateTo = $state('');
  retrievalRelationType = $state('');
  retrievalLimit = $state(10);

  // ── Retrieval results ─────────────────────────────────────
  retrievalLoading = $state(false);
  retrievalError = $state('');
  retrievalResults = $state<PlanArchiveRetrievalResult[]>([]);
  retrievalTotal = $state(0);

  // ── Metrics ───────────────────────────────────────────────
  metricsLoading = $state(false);
  metricsError = $state('');
  retrievalMetrics = $state<PlanArchiveMetricsResponse | null>(null);

  // ── Index ─────────────────────────────────────────────────
  indexLimit = $state(100);
  indexForce = $state(false);
  indexSince = $state('');
  indexLoading = $state(false);
  indexError = $state('');
  indexResult = $state<PlanArchiveIndexResponse | null>(null);

  // ── Cross-repo index ──────────────────────────────────────
  crossRepoIndexLoading = $state(false);
  crossRepoIndexResult = $state<PlanArchiveCrossRepoIndexResponse | null>(null);

  // ── Manual analyze (per-record analyze tab) ───────────────
  manualAnalyzeProvider = $state('codex');
  manualAnalyzeModel = $state('gpt-5.5');
  manualAnalyzeTimeout = $state(120);
  manualAnalyzeLoading = $state(false);
  manualAnalyzeResult = $state<PlanArchiveAnalyzeResponse | null>(null);
  manualAnalyzeError = $state('');
  manualConfirmingApply = $state(false);

  // ── Manual reanalyze (per-record queue 요청) ──────────────
  queueAnalyzeProvider = $state('');
  queueAnalyzeModel = $state('');
  queueAnalyzeLoading = $state(false);
  appliedRequestId = $state<number | null>(null);

  resetForRecord() {
    this.manualAnalyzeResult = null;
    this.manualAnalyzeError = '';
    this.manualConfirmingApply = false;
    this.appliedRequestId = null;
  }
}

export function createArchiveResidualState(): ArchiveResidualState {
  return new ArchiveResidualState();
}
