const REAL_LOG_MARKERS = [
	"[TRIGGER]",
	"[RUN_META]",
	"[PLAN-RUNNER",
	"[ERROR]",
	"[WARN]",
	"[INFO]",
	"WRITE_SCOPE_REROUTE_REQUIRED",
];

export function isStartOnlyRecentLog(lines) {
	const nonEmpty = (lines ?? []).map((line) => String(line).trim()).filter(Boolean);
	if (nonEmpty.length === 0 || nonEmpty.length > 3) return false;
	if (nonEmpty.some((line) => REAL_LOG_MARKERS.some((marker) => line.includes(marker)))) {
		return false;
	}
	return nonEmpty.every(
		(line) =>
			line.includes("START") ||
			line.includes("log_path=") ||
			line.toLowerCase().includes("marker"),
	);
}
