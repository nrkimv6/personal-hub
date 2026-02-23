/// <reference types="@sveltejs/kit" />
/// <reference lib="webworker" />

declare let self: ServiceWorkerGlobalScope;

import { build, files, version } from '$service-worker';

const CACHE_NAME = `cache-${version}`;
const ASSETS = [...build, ...files];

/**
 * Service Worker용 타임아웃 fetch
 * - 정적 자산 로드 시 5초 타임아웃
 * - 타임아웃 시 캐시 우선 전략으로 전환
 */
async function fetchWithTimeout(request: Request, timeout = 5000): Promise<Response> {
	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), timeout);

	try {
		const response = await fetch(request, { signal: controller.signal });
		clearTimeout(timeoutId);
		return response;
	} catch (error) {
		clearTimeout(timeoutId);
		if (error instanceof Error && error.name === 'AbortError') {
			// 타임아웃 시 캐시 우선 전략
			const cached = await caches.match(request);
			if (cached) return cached;
			throw new Error('Network timeout and no cache');
		}
		throw error;
	}
}

// 설치 시 정적 자산 캐시 + 즉시 활성화
self.addEventListener('install', (event) => {
	event.waitUntil(
		caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
	);
});

// 활성화 시 이전 캐시 정리 + 즉시 제어권 획득
self.addEventListener('activate', (event) => {
	event.waitUntil(
		caches.keys().then((keys) =>
			Promise.all(
				keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
			)
		).then(() => self.clients.claim())
	);
});

// 네트워크 우선, 실패 시 캐시 (타임아웃 5초)
self.addEventListener('fetch', (event) => {
	if (event.request.method !== 'GET') return;

	const url = new URL(event.request.url);

	// API 요청, SSE 스트림, 외부 URL은 Service Worker가 가로채지 않음
	if (url.pathname.startsWith('/api/')) return;
	if (event.request.headers.get('accept')?.includes('text/event-stream')) return;
	if (url.origin !== self.location.origin) return;

	event.respondWith(
		fetchWithTimeout(event.request)
			.then((response) => {
				const clone = response.clone();
				caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
				return response;
			})
			.catch(() => caches.match(event.request).then((r) => r || new Response('Offline')))
	);
});
