import { isAbortError } from '../utils/isAbortError.js';

/**
 * @typedef {{ kind: 'abort'; error: Error }} AbortRequestFailure
 * @typedef {{ kind: 'timeout'; error: Error }} TimeoutRequestFailure
 * @typedef {{ kind: 'connection'; error: Error; message: string; url: string }} ConnectionRequestFailure
 * @typedef {AbortRequestFailure | TimeoutRequestFailure | ConnectionRequestFailure} RequestFailure
 */

/**
 * @param {unknown} error
 * @param {string} url
 * @returns {RequestFailure}
 */
export function classifyRequestFailure(error, url) {
	const normalizedError = error instanceof Error ? error : new Error(String(error));

	if (isAbortError(normalizedError)) {
		return { kind: 'abort', error: normalizedError };
	}

	if (normalizedError.message.includes('타임아웃')) {
		return { kind: 'timeout', error: normalizedError };
	}

	return {
		kind: 'connection',
		error: normalizedError,
		message: 'API 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.',
		url
	};
}
