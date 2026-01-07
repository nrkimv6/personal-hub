/**
 * Native Share Handler - Capacitor 앱에서 Share Intent 처리
 *
 * Android에서 다른 앱이 URL을 공유하면 MainActivity.java가
 * window.handleNativeShare()를 호출하여 이 핸들러로 전달합니다.
 */
import { browser } from '$app/environment';
import { crawlApi } from '$lib/api';
import { toast } from '$lib/stores/toast';

// 공유 처리 중인지 여부 (중복 방지)
let isProcessing = false;

// WebView 준비 전 수신된 공유 URL 큐
let pendingShareUrl: string | null = null;

/**
 * 공유된 텍스트에서 URL 추출
 */
function extractUrl(text: string): string | null {
	const urlMatch = text.match(/https?:\/\/[^\s<>"']+/);
	return urlMatch ? urlMatch[0] : null;
}

/**
 * URL 크롤링 요청 처리
 */
async function processShare(sharedText: string): Promise<void> {
	if (isProcessing) {
		console.log('[NativeShare] Already processing, skipping');
		return;
	}

	const url = extractUrl(sharedText);
	if (!url) {
		toast.error('URL을 찾을 수 없습니다');
		return;
	}

	isProcessing = true;

	try {
		await crawlApi.createUrlRequest({
			url,
			auto_analyze: true,
			priority: 0
		});

		toast.success('등록 완료');
	} catch (error) {
		console.error('[NativeShare] Failed to create crawl request:', error);
		toast.error('등록 실패');
	} finally {
		isProcessing = false;
	}
}

/**
 * Native Share Handler 초기화
 * 앱 시작 시 +layout.svelte의 onMount에서 호출
 */
export function initNativeShareHandler(): void {
	if (!browser) return;

	// Capacitor 네이티브 앱이 아닌 경우 스킵
	const isNative = (window as any).Capacitor?.isNativePlatform?.();
	if (!isNative) {
		console.log('[NativeShare] Not a native platform, skipping initialization');
		return;
	}

	console.log('[NativeShare] Initializing native share handler');

	// 네이티브에서 호출할 전역 함수 등록
	(window as any).handleNativeShare = (sharedText: string) => {
		console.log('[NativeShare] Received share:', sharedText?.substring(0, 100));
		processShare(sharedText);
	};

	// 대기 중인 공유 URL 처리 (앱 시작 시 공유로 열린 경우)
	if (pendingShareUrl) {
		console.log('[NativeShare] Processing pending share URL');
		processShare(pendingShareUrl);
		pendingShareUrl = null;
	}
}

/**
 * 대기 중인 공유 URL 저장 (MainActivity에서 WebView 준비 전 호출 시)
 */
export function setPendingShare(url: string): void {
	pendingShareUrl = url;
}
