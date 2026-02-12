/**
 * Base64 URL-safe 인코딩/디코딩 유틸리티
 *
 * RFC 4648 Section 5 표준을 따릅니다:
 * - `+` → `-`
 * - `/` → `_`
 * - padding `=` 제거
 */

/**
 * 파일 경로를 Base64 URL-safe 문자열로 인코딩
 *
 * @param path - 인코딩할 파일 경로 (Windows 경로 포함)
 * @returns Base64 URL-safe 인코딩된 문자열
 *
 * @example
 * // Windows 경로
 * encodePathToBase64('D:\\work\\project\\service\\wtools\\plan.md')
 * // => 'RDpcd29ya1xwcm9qZWN0XHNlcnZpY2Vcd3Rvb2xzXHBsYW4ubWQ'
 *
 * @example
 * // Linux 경로
 * encodePathToBase64('/home/user/project/plan.md')
 * // => 'L2hvbWUvdXNlci9wcm9qZWN0L3BsYW4ubWQ'
 */
export function encodePathToBase64(path: string): string {
	// UTF-8 바이트 배열로 변환
	const bytes = new TextEncoder().encode(path);

	// 바이트 배열을 문자열로 변환 (btoa 입력용)
	let binary = '';
	bytes.forEach(byte => {
		binary += String.fromCharCode(byte);
	});

	// Base64 인코딩 + URL-safe 문자 치환
	return btoa(binary)
		.replace(/\+/g, '-')  // + → -
		.replace(/\//g, '_')  // / → _
		.replace(/=+$/, '');  // padding 제거
}

/**
 * Base64 URL-safe 문자열을 파일 경로로 디코딩
 *
 * @param encoded - Base64 URL-safe 인코딩된 문자열
 * @returns 디코딩된 파일 경로
 *
 * @example
 * decodePathFromBase64('RDpcd29ya1xwcm9qZWN0XHNlcnZpY2Vcd3Rvb2xzXHBsYW4ubWQ')
 * // => 'D:\\work\\project\\service\\wtools\\plan.md'
 */
export function decodePathFromBase64(encoded: string): string {
	// URL-safe 문자 복원
	let base64 = encoded
		.replace(/-/g, '+')  // - → +
		.replace(/_/g, '/'); // _ → /

	// padding 복원 (4의 배수로 맞춤)
	const padding = (4 - (base64.length % 4)) % 4;
	base64 += '='.repeat(padding);

	// Base64 디코딩
	const binary = atob(base64);

	// 문자열을 바이트 배열로 변환
	const bytes = new Uint8Array(binary.length);
	for (let i = 0; i < binary.length; i++) {
		bytes[i] = binary.charCodeAt(i);
	}

	// UTF-8 문자열로 변환
	return new TextDecoder().decode(bytes);
}
