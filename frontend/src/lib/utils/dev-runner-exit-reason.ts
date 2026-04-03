export interface ExitReasonDisplay {
	reason: string;
	statusIcon: string;
	dotClass: string;
	bannerClass: string;
	bannerText: string;
}

const BASE_BANNER =
	'px-3 py-1.5 border-b text-xs shrink-0 flex items-center gap-2';

const DISPLAY_MAP: Record<string, Omit<ExitReasonDisplay, 'reason'>> = {
	completed: {
		statusIcon: '완료',
		dotClass: 'bg-green-500',
		bannerClass: `${BASE_BANNER} bg-green-900/40 border-green-700/50 text-green-300`,
		bannerText: '실행 완료 — 로그 파일에서 계속 볼 수 있습니다'
	},
	no_progress: {
		statusIcon: '⏸️ 중단',
		dotClass: 'bg-yellow-500',
		bannerClass: `${BASE_BANNER} bg-yellow-900/40 border-yellow-700/50 text-yellow-300`,
		bannerText: '진전 없음으로 중단'
	},
	rate_limit: {
		statusIcon: '⚠️ 제한',
		dotClass: 'bg-yellow-500',
		bannerClass: `${BASE_BANNER} bg-yellow-900/40 border-yellow-700/50 text-yellow-300`,
		bannerText: 'Rate limit으로 중단'
	},
	quota_exhausted: {
		statusIcon: '⚠️ Quota',
		dotClass: 'bg-yellow-500',
		bannerClass: `${BASE_BANNER} bg-yellow-900/40 border-yellow-700/50 text-yellow-300`,
		bannerText: 'Quota 소진으로 중단'
	},
	merge_failed: {
		statusIcon: '❌ 머지 실패',
		dotClass: 'bg-red-500',
		bannerClass: `${BASE_BANNER} bg-red-900/40 border-red-700/50 text-red-300`,
		bannerText: '머지 실패 — 로그를 확인하세요'
	},
	commit_failed: {
		statusIcon: '⚠️ 커밋 실패',
		dotClass: 'bg-orange-500',
		bannerClass: `${BASE_BANNER} bg-orange-900/40 border-orange-700/50 text-orange-300`,
		bannerText: '커밋 실패 — 로그를 확인하세요'
	},
	auto_plan_failed: {
		statusIcon: '⚠️ 자동 계획 실패',
		dotClass: 'bg-orange-500',
		bannerClass: `${BASE_BANNER} bg-orange-900/40 border-orange-700/50 text-orange-300`,
		bannerText: '자동 계획 단계 실패 — 로그를 확인하세요'
	},
	error: {
		statusIcon: '❌ 에러',
		dotClass: 'bg-red-500',
		bannerClass: `${BASE_BANNER} bg-red-900/40 border-red-700/50 text-red-300`,
		bannerText: '에러로 중단'
	},
	auto_done_failed: {
		statusIcon: '❌ 완료 처리 실패',
		dotClass: 'bg-red-500',
		bannerClass: `${BASE_BANNER} bg-red-900/40 border-red-700/50 text-red-300`,
		bannerText: '완료 처리 실패 — 로그를 확인하세요'
	},
	stopped: {
		statusIcon: '⏹ 중지',
		dotClass: 'bg-muted-foreground',
		bannerClass: `${BASE_BANNER} bg-gray-900/40 border-gray-700/50 text-gray-300`,
		bannerText: '사용자에 의해 중지됨'
	},
	on_hold: {
		statusIcon: '⏸️ 보류',
		dotClass: 'bg-yellow-500',
		bannerClass: `${BASE_BANNER} bg-gray-900/40 border-gray-700/50 text-gray-300`,
		bannerText: '보류 상태 — 종료'
	},
	archived: {
		statusIcon: '📁 아카이브됨',
		dotClass: 'bg-muted-foreground',
		bannerClass: `${BASE_BANNER} bg-gray-900/40 border-gray-700/50 text-gray-300`,
		bannerText: 'Plan 아카이브됨'
	}
};

const FALLBACK_DISPLAY: Omit<ExitReasonDisplay, 'reason'> = {
	statusIcon: '⁉️ 미상',
	dotClass: 'bg-muted-foreground',
	bannerClass: `${BASE_BANNER} bg-gray-900/40 border-gray-700/50 text-gray-300`,
	bannerText: '종료됨'
};

export function normalizeExitReason(reason?: string | null): string {
	const normalized = String(reason ?? 'unknown').trim().toLowerCase();
	if (!normalized) return 'unknown';
	return normalized === 'rate_limited' ? 'rate_limit' : normalized;
}

export function getExitReasonDisplay(reason?: string | null): ExitReasonDisplay {
	const normalized = normalizeExitReason(reason);
	const resolved = DISPLAY_MAP[normalized] ?? {
		...FALLBACK_DISPLAY,
		bannerText: `종료됨 (${normalized})`
	};
	return {
		reason: normalized,
		...resolved
	};
}
