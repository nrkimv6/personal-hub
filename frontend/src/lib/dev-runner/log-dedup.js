const WRAPPER_PREFIX_RE = /^\[(PR|PS):[^\]]+\]\s*/;

/**
 * [PR:...] / [PS:...] wrapper prefix를 제거한 라인 반환.
 * dedup fingerprint 계산에 사용해 같은 본문의 다른 wrapper prefix 라인을 동일 취급한다.
 * @param {string} line
 * @returns {string}
 */
export function stripWrapperPrefix(line) {
	return line.replace(WRAPPER_PREFIX_RE, '');
}

/**
 * FNV-1a(32bit) 기반 라인 fingerprint.
 * runner_id를 포함해 runner 간 동일 라인 충돌을 분리한다.
 * @param {string} runnerId
 * @param {string} line
 * @returns {string}
 */
export function lineFingerprint(runnerId, line) {
	let hash = 2166136261;
	const source = `${runnerId}\u0000${line}`;
	for (let i = 0; i < source.length; i++) {
		hash ^= source.charCodeAt(i);
		hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
	}
	return (hash >>> 0).toString(16);
}

/**
 * 로그 주입 dedup 판정.
 * - 빈 라인(우측 공백 제거 후)은 skip
 * - runner별 최근 fingerprint window에 이미 있으면 skip
 * - 신규면 window에 추가
 * @param {Map<string, string[]>} fingerprintMap
 * @param {string} runnerId
 * @param {string} line
 * @param {number} [limit=160]
 * @returns {boolean}
 */
export function shouldSkipInjectedLine(fingerprintMap, runnerId, line, limit = 160) {
	const normalized = stripWrapperPrefix(line.trimEnd());
	if (!normalized) return true;
	const fp = lineFingerprint(runnerId, normalized);
	const recent = fingerprintMap.get(runnerId) ?? [];
	if (recent.includes(fp)) return true;
	recent.push(fp);
	if (recent.length > limit) {
		recent.shift();
	}
	fingerprintMap.set(runnerId, recent);
	return false;
}
