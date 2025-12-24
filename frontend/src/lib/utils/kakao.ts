/**
 * 카카오톡 공유 유틸리티
 *
 * 사용 전 필요사항:
 * 1. Kakao Developers에서 앱 등록 및 JavaScript 키 발급
 * 2. frontend/.env.local에 PUBLIC_KAKAO_APP_KEY 설정
 * 3. Kakao Developers에서 플랫폼 > Web > 도메인 등록
 */
import { browser } from '$app/environment';
import { env } from '$env/dynamic/public';

// 환경변수에서 카카오 앱 키 가져오기 (없으면 빈 문자열)
const PUBLIC_KAKAO_APP_KEY = env.PUBLIC_KAKAO_APP_KEY || '';

// Kakao SDK 타입 선언
declare global {
	interface Window {
		Kakao?: {
			init: (appKey: string) => void;
			isInitialized: () => boolean;
			Share: {
				sendDefault: (options: KakaoShareDefaultOptions) => void;
			};
		};
	}
}

interface KakaoShareDefaultOptions {
	objectType: 'feed' | 'list' | 'location' | 'commerce' | 'text';
	content: {
		title: string;
		description?: string;
		imageUrl: string;
		link: {
			mobileWebUrl: string;
			webUrl: string;
		};
	};
	buttons?: Array<{
		title: string;
		link: {
			mobileWebUrl: string;
			webUrl: string;
		};
	}>;
}

export interface KakaoShareOptions {
	imageUrl: string;
	title: string;
	description?: string;
	linkUrl: string;
}

let initialized = false;

/**
 * Kakao SDK 초기화
 * @returns 초기화 성공 여부
 */
export function initKakao(): boolean {
	if (!browser || !window.Kakao) return false;
	if (initialized) return true;

	try {
		if (!window.Kakao.isInitialized() && PUBLIC_KAKAO_APP_KEY) {
			window.Kakao.init(PUBLIC_KAKAO_APP_KEY);
		}
		initialized = window.Kakao.isInitialized();
		return initialized;
	} catch (error) {
		console.error('Kakao SDK 초기화 실패:', error);
		return false;
	}
}

/**
 * 카카오톡으로 피드 공유
 */
export function shareToKakao(options: KakaoShareOptions): Promise<void> {
	return new Promise((resolve, reject) => {
		if (!initKakao()) {
			reject(new Error('Kakao SDK가 초기화되지 않았습니다. 앱 키를 확인하세요.'));
			return;
		}

		try {
			window.Kakao!.Share.sendDefault({
				objectType: 'feed',
				content: {
					title: options.title,
					description: options.description || '',
					imageUrl: options.imageUrl,
					link: {
						mobileWebUrl: options.linkUrl,
						webUrl: options.linkUrl
					}
				},
				buttons: [
					{
						title: '원본 보기',
						link: {
							mobileWebUrl: options.linkUrl,
							webUrl: options.linkUrl
						}
					}
				]
			});
			resolve();
		} catch (error) {
			reject(error);
		}
	});
}

/**
 * 카카오톡 공유 가능 여부 확인
 */
export function isKakaoAvailable(): boolean {
	if (!browser) return false;
	return !!window.Kakao && !!PUBLIC_KAKAO_APP_KEY;
}

/**
 * 공유 (카카오 우선, 폴백 지원)
 * 1. 카카오톡 SDK
 * 2. Web Share API (모바일)
 * 3. 클립보드 복사
 */
export async function shareWithFallback(options: KakaoShareOptions): Promise<'kakao' | 'webshare' | 'clipboard'> {
	// 1. 카카오 SDK 시도
	if (isKakaoAvailable()) {
		try {
			await shareToKakao(options);
			return 'kakao';
		} catch (error) {
			console.warn('카카오 공유 실패, 폴백 시도:', error);
		}
	}

	// 2. Web Share API 폴백 (모바일)
	if (browser && navigator.share) {
		try {
			await navigator.share({
				title: options.title,
				text: options.description,
				url: options.linkUrl
			});
			return 'webshare';
		} catch (error) {
			// 사용자가 취소한 경우
			if ((error as Error).name === 'AbortError') {
				throw error;
			}
			console.warn('Web Share API 실패:', error);
		}
	}

	// 3. 클립보드 복사 폴백
	if (browser && navigator.clipboard) {
		await navigator.clipboard.writeText(options.linkUrl);
		return 'clipboard';
	}

	throw new Error('공유 기능을 사용할 수 없습니다.');
}
