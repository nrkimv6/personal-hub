/**
 * Dev Runner Plans Store
 *
 * plans 목록을 공유 상태로 관리. DevRunnerTab, PlanListTab 등 여러 컴포넌트가
 * 동일한 fetch Promise를 공유하여 중복 요청을 방지한다.
 */
import { writable } from 'svelte/store';
import { devRunnerPlanApi, type PlanFileResponse } from '$lib/api/dev-runner';

export const plansStore = writable<PlanFileResponse[]>([]);
export const plansLoadingStore = writable<boolean>(false);

let _fetchPromise: Promise<PlanFileResponse[]> | null = null;

/**
 * plans 목록을 fetch. 이미 진행 중인 요청이 있으면 해당 Promise를 재사용(dedup).
 */
export async function fetchPlans(): Promise<PlanFileResponse[]> {
	if (_fetchPromise) return _fetchPromise;

	plansLoadingStore.set(true);
	_fetchPromise = devRunnerPlanApi.list().then((data) => {
		plansStore.set(data);
		return data;
	}).finally(() => {
		_fetchPromise = null;
		plansLoadingStore.set(false);
	});

	return _fetchPromise;
}

/**
 * 캐시를 무효화하고 즉시 재조회.
 */
export async function invalidatePlans(): Promise<PlanFileResponse[]> {
	_fetchPromise = null;
	return fetchPlans();
}

/**
 * 외부에서 plans를 직접 갱신 (mutation 응답의 plans 필드로 갱신 시 사용).
 */
export function setPlans(plans: PlanFileResponse[]): void {
	plansStore.set(plans);
}
