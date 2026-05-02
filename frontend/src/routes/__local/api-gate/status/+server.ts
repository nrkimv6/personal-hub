import { json } from '@sveltejs/kit';
import { getGateSnapshot } from '$lib/server/api-gate-state';

// SvelteKit server route: available in dev, preview, and production builds.
export function GET() {
	return json(getGateSnapshot());
}
