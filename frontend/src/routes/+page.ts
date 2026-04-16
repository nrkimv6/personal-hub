import { redirect } from '@sveltejs/kit';
import { resolvePublicLandingPath } from '$lib/utils/publicRouteMode';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  throw redirect(302, await resolvePublicLandingPath({ fetch, url }));
};
