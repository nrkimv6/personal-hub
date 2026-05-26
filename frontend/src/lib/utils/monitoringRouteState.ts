import {
	MONITOR_TYPE_META,
	type MonitoringRouteState,
	type MonitorStatus,
	type MonitorSubView,
	type MonitorType,
	type MonitorView
} from '$lib/types/monitoring';

const STATUS_VALUES = new Set<MonitorStatus>(['running', 'idle', 'error', 'disabled']);
const TYPE_VALUES = new Set<MonitorType>(Object.keys(MONITOR_TYPE_META) as MonitorType[]);

function isMonitorType(value: string | null): value is MonitorType {
	return !!value && TYPE_VALUES.has(value as MonitorType);
}

function isMonitorStatus(value: string | null): value is MonitorStatus {
	return !!value && STATUS_VALUES.has(value as MonitorStatus);
}

function decodeOptional(value: string | null): string | null {
	if (!value) return null;
	try {
		return decodeURIComponent(value);
	} catch {
		return value;
	}
}

export function getDefaultMonitorView(type: MonitorType | null): MonitorView {
	return type ? MONITOR_TYPE_META[type].defaultView : 'list';
}

export function getMonitorViews(type: MonitorType | null) {
	return type ? MONITOR_TYPE_META[type].views : [];
}

export function normalizeMonitoringRouteState(state: MonitoringRouteState): MonitoringRouteState {
	if (!state.type) {
		return { ...state, type: null, view: 'list', sub: null, id: null };
	}
	if (state.view === 'list') {
		return { ...state, sub: null, id: null };
	}

	const views = MONITOR_TYPE_META[state.type].views;
	const view = views.some((candidate) => candidate.id === state.view)
		? state.view
		: MONITOR_TYPE_META[state.type].defaultView;
	const viewMeta = views.find((candidate) => candidate.id === view);
	const sub =
		state.sub && viewMeta?.subviews?.some((candidate) => candidate.id === state.sub) ? state.sub : null;

	return { ...state, view, sub };
}

export function parseMonitoringRouteState(url: URL): MonitoringRouteState {
	const rawType = url.searchParams.get('type');
	const type = isMonitorType(rawType) ? rawType : null;
	const view = (url.searchParams.get('view') as MonitorView | null) ?? 'list';
	const rawStatus = url.searchParams.get('status');
	const status = isMonitorStatus(rawStatus) ? rawStatus : null;

	return normalizeMonitoringRouteState({
		type,
		view,
		sub: (url.searchParams.get('sub') as MonitorSubView | null) ?? null,
		id: decodeOptional(url.searchParams.get('id')),
		status
	});
}

export function buildMonitoringHref(
	statePatch: Partial<MonitoringRouteState>,
	currentUrl?: URL | string
): string {
	const baseUrl =
		currentUrl instanceof URL
			? new URL(currentUrl.toString())
			: new URL(currentUrl ?? '/monitoring', 'http://monitor-page.local');
	baseUrl.pathname = '/monitoring';

	const current = parseMonitoringRouteState(baseUrl);
	const typeChanged = Object.prototype.hasOwnProperty.call(statePatch, 'type') && statePatch.type !== current.type;
	const next = normalizeMonitoringRouteState({
		...current,
		...statePatch,
		view: statePatch.view ?? (typeChanged ? getDefaultMonitorView(statePatch.type ?? null) : current.view),
		sub: statePatch.sub ?? (typeChanged ? null : current.sub),
		id: statePatch.id ?? (typeChanged ? null : current.id)
	});

	baseUrl.searchParams.delete('type');
	baseUrl.searchParams.delete('view');
	baseUrl.searchParams.delete('sub');
	baseUrl.searchParams.delete('id');
	baseUrl.searchParams.delete('status');

	if (next.type) baseUrl.searchParams.set('type', next.type);
	if (next.type && next.view !== 'list') baseUrl.searchParams.set('view', next.view);
	if (next.sub) baseUrl.searchParams.set('sub', next.sub);
	// URLSearchParams performs encodeURIComponent-equivalent escaping while keeping read-side decode centralized.
	if (next.id) baseUrl.searchParams.set('id', next.id);
	if (next.status) baseUrl.searchParams.set('status', next.status);

	return `${baseUrl.pathname}${baseUrl.search}`;
}
