/**
 * 로컬스토리지 기반 이벤트 참여 상태 관리
 *
 * 이벤트의 참여 완료 여부를 로컬스토리지에 저장하여 관리
 * (팝업의 방문 상태는 서버 API로 관리됨)
 */

import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';
import { PARTICIPATED_STORAGE_KEY } from '$lib/constants/eventConstants';
import type { Event } from '$lib/types';

// 참여 상태 맵: eventId -> 참여 여부
type ParticipationMap = Record<number, boolean>;

function createLocalParticipationStore() {
	const { subscribe, set, update } = writable<ParticipationMap>({});

	return {
		subscribe,

		/**
		 * 로컬스토리지에서 참여 상태 로드
		 */
		load(): void {
			if (!browser) return;
			try {
				const stored = localStorage.getItem(PARTICIPATED_STORAGE_KEY);
				if (stored) {
					set(JSON.parse(stored));
				}
			} catch (e) {
				console.error('로컬 참여 상태 로드 실패:', e);
				set({});
			}
		},

		/**
		 * 로컬스토리지에 참여 상태 저장
		 */
		save(): void {
			if (!browser) return;
			try {
				const current = get({ subscribe });
				localStorage.setItem(PARTICIPATED_STORAGE_KEY, JSON.stringify(current));
			} catch (e) {
				console.error('로컬 참여 상태 저장 실패:', e);
			}
		},

		/**
		 * 이벤트 참여 여부 확인
		 * 로컬스토리지에 저장된 값이 있으면 사용, 없으면 서버 값 사용
		 */
		isParticipated(event: Event): boolean {
			const current = get({ subscribe });
			if (event.id in current) {
				return current[event.id];
			}
			return event.is_participated;
		},

		/**
		 * 참여 상태 토글
		 */
		toggle(eventId: number, currentState: boolean): void {
			update((state) => {
				const newState = { ...state, [eventId]: !currentState };
				// 저장
				if (browser) {
					try {
						localStorage.setItem(PARTICIPATED_STORAGE_KEY, JSON.stringify(newState));
					} catch (e) {
						console.error('로컬 참여 상태 저장 실패:', e);
					}
				}
				return newState;
			});
		},

		/**
		 * 특정 이벤트의 참여 상태 설정
		 */
		setParticipated(eventId: number, participated: boolean): void {
			update((state) => {
				const newState = { ...state, [eventId]: participated };
				if (browser) {
					try {
						localStorage.setItem(PARTICIPATED_STORAGE_KEY, JSON.stringify(newState));
					} catch (e) {
						console.error('로컬 참여 상태 저장 실패:', e);
					}
				}
				return newState;
			});
		}
	};
}

export const localParticipation = createLocalParticipationStore();
